#!/system/bin/sh

# Magisk automatically extracts the zip into $MODPATH when SKIPUNZIP=0.
SKIPUNZIP=0

ui_print "╔═ Checking environment"
ui_print "║  Arch check..."
ui_print "║  Device arch: $ARCH"

ui_print "║  Checking bundled APKs..."
# Verify the files packed by your GitHub Action are actually present
if [ ! -f "$MODPATH/stock/stock.apk" ]; then
    abort "╚✗ Bundled stock.apk not found! Ensure the GitHub Action packed it into the zip."
fi

if [ ! -f "$MODPATH/patched.apk" ]; then
    abort "╚✗ Bundled patched.apk not found!"
fi
ui_print "╚═ Environment check passed!"

ui_print "- Cleaning up unused architecture binaries..."
case "$ARCH" in
    arm64) KEEP_ARCH="arm64" ;;
    arm) KEEP_ARCH="arm" ;;
    x86_64) KEEP_ARCH="x64" ;;
    x86) KEEP_ARCH="x86" ;;
    *) KEEP_ARCH="arm64" ;;
esac

# Remove directories in bin/ that don't match the current device's architecture[cite: 10]
for BIN_DIR in "$MODPATH/bin/"*; do
    if [ -d "$BIN_DIR" ] && [ "$(basename "$BIN_DIR")" != "$KEEP_ARCH" ]; then
        rm -rf "$BIN_DIR"
    fi
done

# Promote the correct binaries to the root of bin/ and remove the architecture folder
mv -f "$MODPATH/bin/$KEEP_ARCH/"* "$MODPATH/bin/" 2>/dev/null
rm -rf "$MODPATH/bin/$KEEP_ARCH" 2>/dev/null

ui_print "- Setting permissions..."
set_perm_recursive "$MODPATH" 0 0 0755 0644
set_perm_recursive "$MODPATH/bin" 0 0 0755 0755

for script in action.sh service.sh uninstall.sh utils.sh; do
    if [ -f "$MODPATH/$script" ]; then
        set_perm "$MODPATH/$script" 0 0 0755
    fi
done
