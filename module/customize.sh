#!/system/bin/sh
export MODULE_HOT_INSTALL_REQUEST="true"
MODDIR="$MODPATH" . "$MODPATH/utils.sh"

# ── helpers ──────────────────────────────────────────────────────────────────
step()  { ui_print ""; ui_print "╔═ $*"; }
info()  { ui_print "║  $*"; }
ok()    { ui_print "╚✓ $*"; }
fail()  { ui_print "╚✗ $*"; abort "$*"; }

pct() {
    # Print a simple ASCII progress bar: pct <label> <0-100>
    local label=$1 p=$2
    local filled=$(( p * 20 / 100 ))
    local empty=$(( 20 - filled ))
    local bar=""
    i=0; while [ $i -lt $filled ]; do bar="${bar}█"; i=$(( i+1 )); done
    i=0; while [ $i -lt $empty  ]; do bar="${bar}░"; i=$(( i+1 )); done
    ui_print "║  [${bar}] ${p}%  ${label}"
}

# ── 1. Environment checks ─────────────────────────────────────────────────────
step "Checking environment"

info "Arch check..."
if [ -n "$MODULE_ARCH" ] && [ "$MODULE_ARCH" != "$ARCH" ]; then
    fail "Wrong arch — device: $ARCH  module: $MODULE_ARCH"
fi

if [ "$ARCH" = "arm" ];   then ARCH_LIB=armeabi-v7a
elif [ "$ARCH" = "arm64" ]; then ARCH_LIB=arm64-v8a
elif [ "$ARCH" = "x86" ];  then ARCH_LIB=x86
elif [ "$ARCH" = "x64" ];  then ARCH_LIB=x86_64
else fail "Unreachable arch: ${ARCH}"; fi
info "Device arch: $ARCH ($ARCH_LIB)"

info "Checking curl..."
if ! command -v curl >/dev/null 2>&1; then
    fail "curl is not available in this environment — cannot download stock APK"
fi
info "curl OK"

info "Checking network..."
if ! curl -sf --max-time 5 "https://www.apkmirror.com" -o /dev/null; then
    fail "No internet access — cannot download stock APK"
fi
info "Network OK"

ok "Environment OK"

# ── 2. Load config ────────────────────────────────────────────────────────────
step "Loading module config"
info "PKG:     $PKG_NAME"
info "Version: $PKG_VER"
info "Arch:    $APK_ARCH"
if [ -z "$APK_URL" ]; then
    fail "APK_URL not set in config — rebuild the module"
fi
info "Source:  $APK_URL"
ok "Config loaded"

# ── 3. Module setup ───────────────────────────────────────────────────────────
step "Setting up module"
info "Setting binary permissions..."
set_perm_recursive "$MODPATH/bin" 0 0 0755 0777
info "Unmounting any previous version..."
umount_all
ok "Module setup done"

# ── 4. Check existing install ─────────────────────────────────────────────────
step "Checking installed app"
IS_SYSTEM_APP=false
INS=true

if ! OP=$(dumpsys package "$PKG_NAME") || [ -z "$OP" ]; then
    info "$PKG_NAME not found — will do a fresh install"
    if pmex install-existing "$PKG_NAME" >/dev/null 2>&1; then
        pmex uninstall-system-updates "$PKG_NAME" >/dev/null 2>&1
    fi
else
    if BASEPATH=$(get_basepath); then
        if [ "${BASEPATH:1:4}" != "data" ]; then
            IS_SYSTEM_APP=true
            info "$PKG_NAME is a system app"
        fi
        VERSION=$(get_app_version)
        if [ "$VERSION" ] && [ "$VERSION" = "$PKG_VER" ]; then
            info "$PKG_NAME $VERSION already installed — skipping install"
            INS=false
        else
            info "Installed: ${VERSION:-none}  →  Module: $PKG_VER"
            info "Will install correct version"
        fi
    else
        info "$PKG_NAME not installed — fresh install"
    fi
fi
ok "App check done"

# ── 5. Download stock APK from APKMirror ──────────────────────────────────────
STOCK_APK="$MODPATH/stock.apk"
STOCK_TMP="$MODPATH/stock.apk.tmp"

if [ "$INS" = true ]; then
    step "Downloading stock APK v$PKG_VER ($APK_ARCH)"
    info "URL: $APK_URL"
    info "Output: $STOCK_APK"
    ui_print ""

    # curl with progress piped through a line-by-line reader
    # --progress-bar prints lines like " 23.4%  45.2M   3.1M/s    0:00:12"
    # We grab the percentage and reprint as our own bar
    LAST_PCT=-1
    curl -L \
        --progress-bar \
        --retry 3 \
        --retry-delay 2 \
        --connect-timeout 15 \
        -H "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36" \
        -H "Referer: https://www.apkmirror.com/" \
        -o "$STOCK_TMP" \
        "$APK_URL" 2>&1 | while IFS= read -r line; do
            # curl progress lines contain % sign
            p=$(echo "$line" | grep -oE '[0-9]+\.[0-9]+%' | tail -1 | tr -d '%' | cut -d. -f1)
            if [ -n "$p" ] && [ "$p" != "$LAST_PCT" ]; then
                LAST_PCT=$p
                pct "Downloading..." "$p"
            fi
        done

    CURL_EXIT=$?
    if [ $CURL_EXIT -ne 0 ] || [ ! -s "$STOCK_TMP" ]; then
        rm -f "$STOCK_TMP"
        fail "Download failed (curl exit $CURL_EXIT)"
    fi

    mv -f "$STOCK_TMP" "$STOCK_APK"
    SZ_BYTES=$(stat -c "%s" "$STOCK_APK" 2>/dev/null || wc -c <"$STOCK_APK")
    SZ_MB=$(( SZ_BYTES / 1024 / 1024 ))
    pct "Download complete" 100
    ok "Downloaded ${SZ_MB}MB → $STOCK_APK"

    # Basic sanity check — APKs start with PK (zip magic bytes)
    step "Verifying downloaded APK"
    MAGIC=$(dd if="$STOCK_APK" bs=2 count=1 2>/dev/null | od -An -tx1 | tr -d ' \n')
    if [ "$MAGIC" != "504b" ]; then
        rm -f "$STOCK_APK"
        fail "Downloaded file is not a valid APK (bad magic bytes: $MAGIC)"
    fi
    ok "APK integrity OK"
fi

# ── 6. Install stock APK ──────────────────────────────────────────────────────
install_stock() {
    step "Installing $PKG_NAME v$PKG_VER"
    info "Disabling package verifier..."
    VERIF1=$(settings get global verifier_verify_adb_installs)
    VERIF2=$(settings get global package_verifier_enable)
    settings put global verifier_verify_adb_installs 0
    settings put global package_verifier_enable 0

    SZ=$(stat -c "%s" "$STOCK_APK" 2>/dev/null || wc -c <"$STOCK_APK")
    info "APK size: $SZ bytes"
    install_err=""

    for IT in 1 2; do
        info "Creating install session (attempt $IT)..."
        if ! SES=$(pmex install-create --user 0 -i com.android.vending -r -S "$SZ"); then
            info "ERROR: install-create failed"
            install_err="$SES"
            break
        fi
        SES=${SES#*[} SES=${SES%]*}
        info "Session ID: $SES"

        info "Writing APK to session..."
        set_perm "$STOCK_APK" 1000 1000 644 u:object_r:apk_data_file:s0
        if ! op=$(pmex install-write -S "$SZ" "$SES" "stock.apk" "$STOCK_APK"); then
            info "ERROR: install-write failed"
            install_err="$op"
            break
        fi
        info "Committing session..."
        if ! op=$(pmex install-commit "$SES"); then
            ui_print "║  $op"
            if echo "$op" | grep -q -e INSTALL_FAILED_VERSION_DOWNGRADE -e INSTALL_FAILED_UPDATE_INCOMPATIBLE -e INSTALL_FAILED_DUPLICATE; then
                if [ "$IS_SYSTEM_APP" = true ]; then
                    info "System app conflict — creating uninstall script..."
                    mkdir -p /data/adb/rvhc/empty /data/adb/post-fs-data.d
                    chcon u:object_r:system_file:s0 /data/adb/rvhc/empty
                    P="/data/adb/post-fs-data.d/$PKG_NAME-uninstall.sh"
                    echo "mount -o bind /data/adb/rvhc/empty ${BASEPATH}" >"$P"
                    chmod +x "$P"
                    info "Uninstall script created"
                    info ""
                    info "Reboot and reflash the module!"
                    install_err=" "
                    break
                fi
                info "Uninstalling existing version..."
                if ! op=$(pmex uninstall --user 0 "$PKG_NAME"); then
                    ui_print "║  $op"
                    if [ $IT = 2 ]; then
                        install_err="ERROR: pm uninstall failed"
                        break
                    fi
                fi
                continue
            fi
            info "ERROR: install-commit failed"
            install_err="$op"
            break
        fi

        if BASEPATH=$(get_basepath); then
            :
        else
            install_err=" "
            break
        fi
        break
    done

    settings put global verifier_verify_adb_installs "$VERIF1"
    settings put global package_verifier_enable "$VERIF2"

    if [ "$install_err" ]; then
        rm -f "$STOCK_APK"
        fail "$install_err"
    fi
    ok "Installed $PKG_NAME v$PKG_VER"
}

if [ "$INS" = true ]; then
    install_stock || abort
fi

# ── 7. Extract native libs ────────────────────────────────────────────────────
BASEPATHLIB="${BASEPATH}/lib/${ARCH}"
if [ "$INS" = true ] || [ -z "$(ls -A1 "$BASEPATHLIB" 2>/dev/null)" ]; then
    step "Extracting native libs"
    info "Target: $BASEPATHLIB"
    info "Extracting lib/${ARCH_LIB}/* from stock APK..."
    if [ ! -d "$BASEPATHLIB" ]; then
        mkdir -p "$BASEPATHLIB"
    else
        rm -f "$BASEPATHLIB"/* >/dev/null 2>&1 || :
    fi
    if op=$(unzip -o -j "$STOCK_APK" "lib/${ARCH_LIB}/*" -d "$BASEPATHLIB" 2>&1); then
        LIB_COUNT=$(ls -1 "$BASEPATHLIB" 2>/dev/null | wc -l)
        set_perm_recursive "${BASEPATH}/lib" 1000 1000 755 755 u:object_r:apk_data_file:s0
        ok "Extracted $LIB_COUNT native lib(s)"
    else
        info "WARNING: extracting native libs failed: $op"
        info "App may still work without them"
    fi
fi

# ── 8. Clean up stock APK (no longer needed) ──────────────────────────────────
step "Cleaning up"
info "Removing stock APK from module dir..."
rm -f "$STOCK_APK"
ok "Cleanup done"

# ── 9. Set up patched APK and mount ──────────────────────────────────────────
step "Mounting patched APK"
info "Setting permissions on patched.apk..."
set_perm "$MODPATH/patched.apk" 1000 1000 644 u:object_r:apk_data_file:s0

info "Moving patched.apk to /data/adb/rvhc/ (root detection evasion)..."
mkdir -p "/data/adb/rvhc"
mv -f "$MODPATH/patched.apk" "$RVPATH"

info "Binding $RVPATH → $BASEPATH/base.apk..."
if ! op=$(su -M -c mount -o bind "$RVPATH" "$BASEPATH/base.apk" 2>&1); then
    info "ERROR: Mount failed!"
    info "$op"
    fail "Mount failed"
fi
info "Stopping $PKG_NAME..."
am force-stop "$PKG_NAME"
ok "Mounted and stopped app"

# ── 10. Optimize ─────────────────────────────────────────────────────────────
step "Optimizing $PKG_NAME (speed-profile)"
info "Running dex compilation — this may take a moment..."
cmd package compile -m speed-profile -f "$PKG_NAME" >/dev/null 2>&1
ok "Optimization done"

# ── 11. KernelSU profile (skipped — Magisk) ──────────────────────────────────
# KSU block intentionally omitted: device uses Magisk

# ── 12. Final cleanup ─────────────────────────────────────────────────────────
step "Final cleanup"
info "Removing module binaries..."
rm -rf "${MODPATH:?}/bin"
info "Saving module.prop..."
cp -f "$MODPATH/module.prop" "$MODPATH/module.prop.orig"
ok "All done"

ui_print ""
ui_print "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
ui_print "  ✓ $PKG_NAME v$PKG_VER installed"
ui_print "  ✓ Patched APK mounted"
ui_print "  ✓ No reboot needed"
ui_print "    by j-hc (github.com/j-hc)"
ui_print "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
ui_print ""
