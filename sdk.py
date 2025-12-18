import sys
from pathlib import Path
from platformio.package import version


def get_sdk_location(platform):
    return Path(platform.get_package_dir("framework-zephyr")) / "nrfutil_sdk"


def get_sdk_version(platform):
    return f"v{version.get_original_version(platform.get_package_version("framework-zephyr").split("+")[0])}"


def get_nrfutil(platform):
    try:
        import nrfutil
    except ImportError:
        nrfutil_root = Path(platform.get_package_dir("tool-nordic-nrfutil"))
        if not nrfutil_root.is_dir():
            raise RuntimeError("nrfutil directory not found")
        sys.path.append(str(nrfutil_root))
        import nrfutil
    return nrfutil.setup()


def get_sdk(platform):
    nrfutil = get_nrfutil(platform)
    return nrfutil.get_sdk(get_sdk_version(platform), get_sdk_location(platform))


def install_sdk(platform):
    nrfutil = get_nrfutil(platform)
    return nrfutil.install_sdk(get_sdk_version(platform), get_sdk_location(platform))


def get_uf2conv(platform):
    nrfutil = get_nrfutil(platform)
    sdk = nrfutil.get_sdk(get_sdk_version(platform), get_sdk_location(platform))
    uf2conv = sdk.sdk_path / "zephyr" / "scripts" / "build" / "uf2conv.py"
    if not uf2conv.is_file():
        raise RuntimeError(f"uf2conv.py not found at {uf2conv}")
    return uf2conv
