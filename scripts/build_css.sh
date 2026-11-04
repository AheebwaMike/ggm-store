#!/usr/bin/env bash
# Builds static/css/tailwind.css from the templates, using the standalone Tailwind CLI
# (no Node needed). Used by build.sh on Render; also works on Linux and macOS.
set -o errexit

TAILWIND_VERSION="3.4.17"
cd "$(dirname "$0")/.."

case "$(uname -s)-$(uname -m)" in
  Linux-x86_64)  ASSET="tailwindcss-linux-x64" ;;
  Linux-aarch64) ASSET="tailwindcss-linux-arm64" ;;
  Darwin-arm64)  ASSET="tailwindcss-macos-arm64" ;;
  Darwin-x86_64) ASSET="tailwindcss-macos-x64" ;;
  *) echo "Unsupported platform: $(uname -s)-$(uname -m)" >&2; exit 1 ;;
esac

TOOL="tools/tailwindcss-${TAILWIND_VERSION}"
if [ ! -x "$TOOL" ]; then
  echo "Downloading Tailwind CLI ${TAILWIND_VERSION} (${ASSET})..."
  mkdir -p tools
  curl -fsSL -o "$TOOL" "https://github.com/tailwindlabs/tailwindcss/releases/download/v${TAILWIND_VERSION}/${ASSET}"
  chmod +x "$TOOL"
fi

echo "Building static/css/tailwind.css..."
mkdir -p static/css
"$TOOL" -c tailwind.config.js -i static/src/tailwind.input.css -o static/css/tailwind.css --minify