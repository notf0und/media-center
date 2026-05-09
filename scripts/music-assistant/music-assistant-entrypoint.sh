#!/bin/sh
set -e

# Update self-signed CA certificates
update-ca-certificates

# Start Music Assistant
exec mass --config /data
