#!/bin/sh

update-ca-certificates
echo "✅ Updated CA Certificates"

exec "$@"
