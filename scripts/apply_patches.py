#!/usr/bin/env python3
"""Apply the patches in patches/ to a target checkout of sap_warn/ai-backend.

Usage:
    python3 scripts/apply_patches.py /path/to/sap_warn/ai-backend            # dry run
    python3 scripts/apply_patches.py /path/to/sap_warn/ai-backend --apply    # write changes

Dry run (default) only checks that every patch would apply cleanly; it makes
no filesystem changes. Pass --apply to actually modify the target checkout.
Each patch is applied with the `patch` CLI (POSIX `patch`, present on macOS
and Linux by default) so the well-tested unified-diff algorithm is reused
instead of reimplemented.
"""
import argparse
import shutil
import subprocess
import sys
from pathlib import Path

PATCHES_DIR = Path(__file__).resolve().parent.parent / "patches"

PATCH_FILES = [
    "01-mv_x_vendor_360.mv.sql.patch",
    "02-mdl_vendor360.mdl.json.patch",
    "03-prompt_sales_rep_rule.prompt.rs.patch",
]


def run_patch(target_dir: Path, patch_path: Path, dry_run: bool) -> bool:
    cmd = ["patch", "-p1"]
    if dry_run:
        cmd.append("--dry-run")
    cmd += ["-i", str(patch_path)]
    result = subprocess.run(cmd, cwd=target_dir, capture_output=True, text=True)
    sys.stdout.write(result.stdout)
    sys.stderr.write(result.stderr)
    return result.returncode == 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target_dir", help="Path to the sap_warn/ai-backend checkout")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually write changes (default is a dry run that changes nothing)",
    )
    args = parser.parse_args()

    target_dir = Path(args.target_dir).resolve()
    if not target_dir.is_dir():
        print(f"error: {target_dir} is not a directory", file=sys.stderr)
        return 1
    if not (target_dir / "Cargo.toml").is_file():
        print(
            f"error: {target_dir} does not look like the ai-backend repo (no Cargo.toml)",
            file=sys.stderr,
        )
        return 1

    if not PATCHES_DIR.is_dir():
        print(f"error: patches directory not found at {PATCHES_DIR}", file=sys.stderr)
        return 1

    if shutil.which("patch") is None:
        print("error: the 'patch' command is not available on this system", file=sys.stderr)
        return 1

    mode = "APPLYING" if args.apply else "DRY RUN (no files will change)"
    print(f"{mode} — target: {target_dir}\n")

    all_ok = True
    for name in PATCH_FILES:
        patch_path = PATCHES_DIR / name
        if not patch_path.is_file():
            print(f"error: missing patch file {patch_path}", file=sys.stderr)
            all_ok = False
            continue
        print(f"=== {name} ===")
        ok = run_patch(target_dir, patch_path, dry_run=not args.apply)
        if not ok:
            print(f"FAILED to apply {name}", file=sys.stderr)
            all_ok = False
        print()

    if not all_ok:
        print("One or more patches failed. No further patches were skipped, but review output above.", file=sys.stderr)
        return 1

    if args.apply:
        print("All patches applied successfully.")
        print("Next: run `cargo fmt --all -- --check && cargo check --workspace --all-targets "
              "&& cargo clippy --workspace --all-targets -- -D warnings && cargo build --workspace` "
              "inside the target repo to verify.")
    else:
        print("All patches would apply cleanly. Re-run with --apply to write the changes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
