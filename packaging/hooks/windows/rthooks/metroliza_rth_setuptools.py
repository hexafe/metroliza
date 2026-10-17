"""Install the bundled setuptools shim without importing compiler integrations.

Equivalent policy to PyInstaller 6.22.3's pyi_rth_setuptools. The Windows
onedir spec includes the installed setuptools distribution metadata, so the
version query does not import setuptools and trigger platform.win32_ver's
shell probe before the application entry point.
"""


def _install_setuptools_shim():
    try:
        import os
        from importlib.metadata import version

        major = int(version("setuptools").split(".")[0])
        default = "stdlib" if major < 60 else "local"
        if os.environ.get("SETUPTOOLS_USE_DISTUTILS", default) == "local":
            import _distutils_hack

            _distutils_hack.add_shim()
    except Exception:
        # Preserve the upstream optional-hook failure boundary.
        pass


_install_setuptools_shim()
del _install_setuptools_shim
