#!/usr/bin/env python3
"""
Build & prepare static files for GitHub Pages deployment.
Outputs the static web demo to the `docs/` folder so it can be deployed
either via GitHub Actions or via GitHub Pages branch setting (/docs).
"""

import os
import shutil
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FRONTEND_DIR = os.path.join(BASE_DIR, "frontend")
IMAGES_DIR = os.path.join(BASE_DIR, "images")
DOCS_DIR = os.path.join(BASE_DIR, "docs")


def build():
    print(f"Building GitHub Pages static export in: {DOCS_DIR}")
    os.makedirs(DOCS_DIR, exist_ok=True)

    # 1. Copy frontend files
    for fname in ["index.html", "style.css", "app.js"]:
        src = os.path.join(FRONTEND_DIR, fname)
        dst = os.path.join(DOCS_DIR, fname)
        if os.path.exists(src):
            shutil.copy2(src, dst)
            print(f"  ✓ Copied {fname}")
        else:
            print(f"  ✗ Warning: {src} not found!", file=sys.stderr)

    # 2. Copy images folder
    dst_images = os.path.join(DOCS_DIR, "images")
    os.makedirs(dst_images, exist_ok=True)
    if os.path.exists(IMAGES_DIR):
        for img_name in os.listdir(IMAGES_DIR):
            if img_name.endswith(".png") or img_name.endswith(".jpg"):
                shutil.copy2(os.path.join(IMAGES_DIR, img_name), os.path.join(dst_images, img_name))
        print(f"  ✓ Copied images to docs/images/")

    # 3. Add .nojekyll to prevent GitHub Pages from processing with Jekyll
    nojekyll_path = os.path.join(DOCS_DIR, ".nojekyll")
    with open(nojekyll_path, "w") as f:
        f.write("")
    print(f"  ✓ Created .nojekyll")

    print("\n✓ GitHub Pages export ready in 'docs/'!")
    print("  You can now either:")
    print("  a) Enable GitHub Pages in your repo settings -> 'Deploy from a branch' -> main /docs")
    print("  b) Push to GitHub and let the GitHub Actions workflow (.github/workflows/deploy.yml) deploy automatically.")


if __name__ == "__main__":
    build()
