import sys
from pathlib import Path
from platformio.package import version


def get_sdk_location(env):
    platform = env.PioPlatform()
    return Path(platform.get_package_dir("framework-zephyr")) / "nrfutil_sdk"


def get_sdk_version(env):
    platform = env.PioPlatform()
    requested_version = env.GetProjectOption("framework_version", None)
    if requested_version:
        return f"v{requested_version}"
    # fall back to default version of this package
    return f"v{version.get_original_version(platform.get_package_version("framework-zephyr").split("+")[0])}"


def get_nrfutil(env):
    platform = env.PioPlatform()
    try:
        import nrfutil
    except ImportError:
        nrfutil_root = Path(platform.get_package_dir("tool-nordic-nrfutil"))
        if not nrfutil_root.is_dir():
            raise RuntimeError("nrfutil directory not found")
        sys.path.append(str(nrfutil_root))
        import nrfutil
    return nrfutil.setup()


def get_sdk(env):
    nrfutil = get_nrfutil(env)
    version = get_sdk_version(env)
    sdk = nrfutil.get_sdk(version, get_sdk_location(env))
    if not sdk:
        raise RuntimeError(
            f"SDK version {version} not found in {get_sdk_location(env)}."
        )
    return sdk


def install_sdk(env):
    nrfutil = get_nrfutil(env)
    version = get_sdk_version(env)
    sdk = nrfutil.get_sdk(version, get_sdk_location(env))
    if sdk:
        print(f"SDK version {version} is already installed.")
        return sdk
    print(f"Installing SDK version {version}...")
    return nrfutil.install_sdk(version, get_sdk_location(env))


def get_uf2conv(env):
    nrfutil = get_nrfutil(env)
    sdk = nrfutil.get_sdk(get_sdk_version(env), get_sdk_location(env))
    uf2conv = sdk.sdk_path / "zephyr" / "scripts" / "build" / "uf2conv.py"
    if not uf2conv.is_file():
        raise RuntimeError(f"uf2conv.py not found at {uf2conv}")
    return uf2conv
