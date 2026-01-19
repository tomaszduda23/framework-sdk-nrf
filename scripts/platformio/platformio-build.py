# Copyright 2014-present PlatformIO <contact@platformio.org>
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import sys
import textwrap
from pathlib import Path
from itertools import chain

from platformio.proc import exec_command
from SCons.Script import ARGUMENTS, Builder

Import("env")


class BuildEnvironment:
    def __init__(self, project_dir: Path, source_dir: Path, build_dir: Path, sdk):
        self.project_dir = project_dir
        self.source_dir = source_dir
        self.build_dir = build_dir
        self.app_dir = project_dir / "zephyr"
        self.sdk = sdk
        self.reconfigure_required = False

    def run(self, cmd: list[str], cwd=None):
        if not cwd:
            cwd = self.sdk.sdk_path
        ret = exec_command(cmd, env=self.sdk.env, cwd=cwd)
        if ret["returncode"] != 0:
            raise RuntimeError(
                f"Command {' '.join(cmd)} failed:\n{ret['out']}\n{ret['err']}"
            )
        return (ret["out"], ret["err"])

    def _is_reconfigure_required(self, board):
        if self.sdk.fresh_install or self.reconfigure_required:
            return True
        cmake_cache_file = self.build_dir / "CMakeCache.txt"
        if not cmake_cache_file.is_file():
            return True
        build_ninja_file = self.build_dir / "build.ninja"
        if not build_ninja_file.is_file():
            return True
        pm_static_file = self.project_dir / "zephyr" / "pm_static.yml"
        if (
            pm_static_file.is_file()
            and pm_static_file.stat().st_mtime > cmake_cache_file.stat().st_mtime
        ):
            # Reconfigure if pm_static.yml has changed
            return True
        board_file = self.project_dir / "boards" / f"{board}.json"
        if board_file.is_file() and board_file.stat().st_mtime > cmake_cache_file.stat().st_mtime:
            # Reconfigure if the board configuration has changed
            return True
        return False

    def _generate_cmake_library_entries(self, libraries):
        include_dirs = set()
        libs = []
        for l in libraries:
            lib = f"zephyr_library_named({l['name']})"
            lib += f"\nzephyr_library_sources({' '.join(l['sources'])})"
            lib += (
                f"\nzephyr_library_include_directories({' '.join(l['include_dirs'])})"
            )
            include_dirs.update(l["include_dirs"])
            if l["build_flags"]:
                lib += f"\nzephyr_library_compile_options({' '.join(l['build_flags'])})"
            for d in l.get("dependencies", []):
                lib += f"\nzephyr_library_link_libraries({d})"
            libs.append(lib)
        return libs, include_dirs

    def _generate_project_files(
        self,
        build_flags: list[str],
        link_flags: list[str],
        libraries: list[dict],
        source_files: list[Path],
    ):
        libs, include_dirs = self._generate_cmake_library_entries(libraries)
        sources = [str(f.relative_to(self.app_dir, walk_up=True)) for f in source_files]
        self.app_dir.mkdir(parents=True, exist_ok=True)
        cmake_file = self.app_dir / "CMakeLists.txt"
        cmake_tpl = textwrap.dedent(
            f"""
            cmake_minimum_required(VERSION 3.20.0)

            set(Zephyr_DIR "$ENV{{ZEPHYR_BASE}}/share/zephyr-package/cmake/")

            find_package(Zephyr)

            project({self.project_dir.name})

            {'\n'.join(libs)}

            zephyr_compile_options($<$<COMPILE_LANGUAGE:CXX>:{' '.join(build_flags)}>)
            zephyr_include_directories({' '.join(include_dirs)})
            zephyr_ld_options({' '.join(link_flags)})

            target_sources(app PRIVATE {" ".join(sources)})
            target_link_libraries(app PRIVATE {" ".join([l['name'] for l in libraries])})
            target_include_directories(app PRIVATE ../src)
            """
        )

        app_tpl = textwrap.dedent(
            """
            #include <zephyr.h>
            void main(void) {}
            """
        )
        if not cmake_file.is_file() or cmake_file.read_text() != cmake_tpl:
            cmake_file.write_text(cmake_tpl)
            self.reconfigure_required = True
        if not any(self.source_dir.iterdir()):
            main_c_file = self.source_dir / "main.c"
            main_c_file.parent.mkdir(parents=True, exist_ok=True)
            main_c_file.write_text(app_tpl)
            self.reconfigure_required = True

    def _set_extra_cmake_args(self, cmake_extra_args: list[str]):
        try:
            old_args, _ = self.run(["west", "config", "build.cmake-args"])
            old_args = old_args.strip().split()
            if sorted(old_args) == sorted(cmake_extra_args):
                return
        except Exception:
            pass

        print("Setting extra CMake args:", cmake_extra_args)
        self.run(
            [
                "west",
                "config",
                "build.cmake-args",
                "--",
                " ".join(cmake_extra_args),
            ]
        )
        self.reconfigure_required = True

    def build(
        self,
        board: str,
        build_flags: list[str],
        link_flags: list[str],
        libraries: list[dict],
        source_files: list[Path],
        sysbuild: bool = True,
        pristine: bool = False,
        verbose: bool = False,
    ):
        self._generate_project_files(build_flags, link_flags, libraries, source_files)

        west_cmd = [
            "west",
            "build",
            "--sysbuild" if sysbuild else "--no-sysbuild",
            (
                "--pristine"
                if pristine or self._is_reconfigure_required(board)
                else "--pristine=auto"
            ),
            "-b",
            board,
            "-d",
            str(self.build_dir),
            str(self.app_dir),
        ]
        print("Building nRF Connect SDK application...")
        if verbose:
            print(" ".join(map(str, west_cmd)))

        out, err = self.run(west_cmd)
        if verbose:
            print(out)
            print(err)


def c_flags_from_env(env):
    return env.get("BUILD_FLAGS", [])


def link_flags_from_env(env):
    return [x for x in env.get("BUILD_FLAGS", []) if x.startswith("-Wl,")]


def source_files_from_env(env):
    files = chain.from_iterable(env.get("PIOBUILDFILES"))
    files = chain.from_iterable([f.sources for f in files])
    files = [Path((f.srcnode().get_abspath())) for f in files]
    files.sort()
    return files


def get_libraries_from_env(env, build_env):
    ret = []
    for dep in env.GetLibBuilders():
        source_files = env.CollectBuildFiles(dep.build_dir, dep.src_dir, dep.src_filter)
        source_files = [f.srcnode() for f in source_files]
        ret.append(
            {
                "name": dep.name,
                "include_dirs": [
                    str(Path(d).relative_to(build_env.app_dir, walk_up=True))
                    for d in dep.get_include_dirs()
                ],
                "build_flags": env.ProcessFlags(dep.build_flags),
                "include_dir": str(
                    Path(dep.include_dir).relative_to(build_env.app_dir, walk_up=True)
                ),
                "sources": [
                    str(
                        Path(s.get_abspath()).relative_to(
                            build_env.app_dir, walk_up=True
                        )
                    )
                    for s in source_files
                ],
                "dependencies": [d['name'] for d in dep.dependencies] if dep.dependencies else [],
            }
        )
        #print(dep.build_flags)
        
    return ret


def west_build(build_env: BuildEnvironment, target, sources, env):
    pristine = env.GetProjectOption("pristine", "False").lower() == "true"
    sysbuild = env.GetProjectOption("sysbuild", "True").lower() == "true"
    board = env.BoardConfig()

    build_env.build(
        board=board.get("build.zephyr.variant", board.id),
        build_flags=c_flags_from_env(env),
        link_flags=link_flags_from_env(env),
        libraries=get_libraries_from_env(env, build_env),
        source_files=sources,
        sysbuild=sysbuild,
        pristine=pristine,
        verbose=int(ARGUMENTS.get("PIOVERBOSE", 0)) > 0,
    )

    return None


def setup_build(build_env):
    env["BUILDERS"]["WestBuilder"] = Builder(
        action=lambda target, source, env: west_build(
            build_env, target, source_files_from_env(env), env
        ),
    )


platform = env.PioPlatform()
print("Running nrfutil SDK setup...")
sys.path.append(platform.get_package_dir("framework-zephyr"))
import sdk

nrf_sdk = sdk.install_sdk(env)

build_env = BuildEnvironment(
    project_dir=Path(env.subst("$PROJECT_DIR")),
    source_dir=Path(env.subst("$PROJECT_SRC_DIR")),
    build_dir=Path(env.subst("$BUILD_DIR")),
    sdk=nrf_sdk,
)
setup_build(build_env)
