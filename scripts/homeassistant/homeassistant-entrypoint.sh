#!/bin/sh

update-ca-certificates
echo "✅ Updated CA Certificates"

chmod 700 /root/.ssh
chmod 600 /root/.ssh/config
chmod 600 /root/.ssh/id_rsa
chmod 644 /root/.ssh/id_rsa.pub
chown -R root:root /root/.ssh
echo "✅ Fixed permissions to /root/.ssh"

exec "$@"
