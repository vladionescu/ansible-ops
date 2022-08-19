#!/bin/bash

cd $RENEWED_LINEAGE
cat fullchain.pem privkey.pem > everything.pem
docker kill -s HUP haproxy
