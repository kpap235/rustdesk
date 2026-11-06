#!/bin/sh
# Creates .env with fresh random secrets. Run once on the VPS: sh setup.sh
set -e
[ -f .env ] && { echo ".env already exists - not overwriting"; exit 1; }
rnd() { python3 -c "import secrets;print(secrets.token_urlsafe($1))"; }
FERNET=$(python3 -c "import base64,os;print(base64.urlsafe_b64encode(os.urandom(32)).decode())")
ADMINPW=$(rnd 12)
ENROLL=$(rnd 24)
HUBKEY=$(rnd 32)
MONKEY=$(rnd 32)
cat > .env <<EOT
PANEL_DOMAIN=rustdesk.exelixisnet.gr
PANEL_SESSION_SECRET=$(rnd 48)
PANEL_FERNET_KEY=$FERNET
PANEL_ENROLL_TOKEN=$ENROLL
PANEL_HUB_API_KEY=$HUBKEY
PANEL_MONITOR_API_KEY=$MONKEY
PANEL_ADMIN_USER=admin
PANEL_ADMIN_PASSWORD=$ADMINPW
PANEL_APP_URI=exelixisnetitsupport
EOT
chmod 600 .env
mkdir -p data && chmod 777 data
echo
echo "Created .env. Keep these safe:"
echo "  Panel login:       admin / $ADMINPW   (change it after first login)"
echo "  Enrollment token:  $ENROLL   (add as GitHub secret EXELIXIS_ENROLL_TOKEN)"
echo "  Hub API key:       $HUBKEY   (for ExelixisHub)"
echo "  Monitor API key:   $MONKEY   (for MikroTik VPN Monitoring)"
echo
echo "IMPORTANT: back up .env - PANEL_FERNET_KEY decrypts the stored passwords."
