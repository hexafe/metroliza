"""Verify the two Plotly 2.27.0 distribution files used by Metroliza."""

from hashlib import file_digest
from pathlib import Path


PLOTLY_ASSET_DIRECTORY = Path("metroliza/resources/html_dashboard_assets")
PLOTLY_NOTICE_FILENAME = "plotly.min.js.LICENSE.txt"
PLOTLY_ASSET_HASHES = {
    "plotly-2.27.0.min.js": "7f4930eba8f8541dbec28dca5bd5f787f8eef1cde0369ac9657b70bed230b3e0",
    PLOTLY_NOTICE_FILENAME: "49349c63dd1280d54b6c55d4573c672374bacc380ec192b4904852df083ace34",
}


def verified_plotly_files(asset_directory: Path) -> tuple[Path, ...]:
    """Fail before packaging if either exact-version asset is absent or modified."""
    result = []
    for name, expected in PLOTLY_ASSET_HASHES.items():
        path = asset_directory / name
        if not path.is_file():
            raise FileNotFoundError(f"Required Plotly distribution asset is missing: {path}")
        with path.open("rb") as stream:
            observed = file_digest(stream, "sha256").hexdigest()
        if observed != expected:
            raise ValueError(f"Plotly distribution asset has an unexpected SHA-256: {path}")
        result.append(path)
    return tuple(result)


def plotly_inventory(asset_directory: Path) -> dict:
    return {
        "version": "2.27.0",
        "source": "https://registry.npmjs.org/plotly.js/-/plotly.js-2.27.0.tgz",
        "files": [
            {"name": path.name, "sha256": PLOTLY_ASSET_HASHES[path.name]}
            for path in verified_plotly_files(asset_directory)
        ],
    }


if __name__ == "__main__":
    verified_plotly_files(Path(__file__).resolve().parents[1] / "src" / PLOTLY_ASSET_DIRECTORY)
