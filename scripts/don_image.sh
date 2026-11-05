#!/usr/bin/env bash
# P287: xoa image cu trong Artifact Registry, moi image (package) GIU N ban moi nhat.
# Dung quyen deleteArtifacts (vai tro Repository Administrator) — khong can quyen
# dat cleanup policy. Khong bao gio xoa image dang chay tren Cloud Run.
#   bash scripts/don_image.sh thu|that [N]
set -u
CHE_DO="${1:-thu}"; GIU="${2:-10}"
P=bingo18-predictor
DANG_CHAY=$(gcloud run services describe bingo18 --region asia-southeast1 --project $P \
  --format='value(spec.template.spec.containers[0].image)' 2>/dev/null)
echo "Che do: $CHE_DO | giu $GIU ban moi nhat moi image | dang chay: $DANG_CHAY"
TONG_XOA=0
for KHO in asia-southeast1-docker.pkg.dev/$P/bingo18-images \
           asia-southeast1-docker.pkg.dev/$P/cloud-run-source-deploy \
           gcr.io/$P asia.gcr.io/$P; do
  echo "=== $KHO ==="
  gcloud artifacts docker images list "$KHO" --include-tags --sort-by=~updateTime \
    --format='value(package,version,tags)' --project $P > /tmp/ds.txt 2>/tmp/loi.txt || { head -3 /tmp/loi.txt; continue; }
  # giu N ban dau tien (moi nhat) cua moi package
  awk -v n="$GIU" '{ dem[$1]++; if (dem[$1] > n) print $1"@"$2"\t"$3 }' /tmp/ds.txt > /tmp/xoa.txt
  echo "  co $(wc -l < /tmp/ds.txt) ban, se xoa $(wc -l < /tmp/xoa.txt)"
  TONG_XOA=$((TONG_XOA + $(wc -l < /tmp/xoa.txt)))
  [ "$CHE_DO" = "that" ] || { head -3 /tmp/xoa.txt | sed 's/^/    vd: /'; continue; }
  OK=0; HONG=0
  while IFS=$'\t' read -r ANH THE; do
    case "$DANG_CHAY" in *"${ANH##*@}"*) echo "  bo qua (dang chay): $ANH"; continue;; esac
    if [ -n "$THE" ] && [ -n "$DANG_CHAY" ] && [ "${DANG_CHAY##*:}" = "$THE" ]; then echo "  bo qua (dang chay): $ANH"; continue; fi
    if gcloud artifacts docker images delete "$ANH" --delete-tags --quiet --async --project $P >/dev/null 2>/tmp/e.txt; then
      OK=$((OK+1))
    else
      HONG=$((HONG+1)); [ "$HONG" -le 2 ] && head -3 /tmp/e.txt
      grep -q PERMISSION_DENIED /tmp/e.txt && { echo "  THIEU QUYEN xoa — dung o kho nay"; break; }
    fi
  done < /tmp/xoa.txt
  echo "  da gui lenh xoa: $OK | loi: $HONG"
done
echo "TONG se xoa / da xu ly: $TONG_XOA"
