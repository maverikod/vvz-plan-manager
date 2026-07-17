#!/usr/bin/env bash
# scripts/release.sh
# ReleaseScript (C-031): the single release pipeline for plan_manager.
# One pipeline run produces the tagged container image, the Docker Hub push,
# and the Ubuntu deb package, and renders the operator documentation from
# the single source (docs/operator/operator_doc.md) into the man page, the
# GNU info document, and the build-time payload embedded for the API
# self-description command. The package version is the single version
# source: the image tag and the deb package version are both derived from
# it, so they always agree. Every stage below echoes its own name, and the
# whole pipeline aborts the build on the first error (set -euo pipefail);
# the documentation divergence gate additionally fails the build explicitly
# if the embedded payload copy differs byte-for-byte from the source
# document.
set -euo pipefail

echo "== stage: read version =="
VERSION="$(python3 -c 'import tomllib;print(tomllib.load(open("pyproject.toml","rb"))["project"]["version"])')"
REPO="${DOCKERHUB_REPO:-vasilyvz/planmgr}"
echo "version=${VERSION} repo=${REPO}"

echo "== stage: run test suite =="
python3 -m pytest -q

echo "== stage: render documentation =="
ADAPTER_VERSION="$(python3 -c 'import tomllib;deps=tomllib.load(open("pyproject.toml","rb"))["project"]["dependencies"];print([d for d in deps if d.startswith("mcp-proxy-adapter")][0])')"
BUILD_DATE="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
mkdir -p plan_manager/_build build/doc

echo "-- writing build_info.json --"
python3 -c "import json; json.dump({'product': 'plan_manager', 'package_version': '${VERSION}', 'adapter_version': '${ADAPTER_VERSION}', 'build_date': '${BUILD_DATE}', 'image_tag': '${VERSION}'}, open('plan_manager/_build/build_info.json', 'w'))"

echo "-- copying operator documentation payload --"
cp docs/operator/operator_doc.md plan_manager/_build/operator_doc.md

echo "-- divergence gate: embedded payload must match the source byte-for-byte --"
cmp docs/operator/operator_doc.md plan_manager/_build/operator_doc.md || { echo "payload diverged"; exit 1; }

echo "-- rendering man page --"
pandoc -s -t man docs/operator/operator_doc.md -o build/doc/planmgr.1

echo "-- rendering info document --"
pandoc -s -t texinfo docs/operator/operator_doc.md -o build/doc/planmgr.texi
makeinfo build/doc/planmgr.texi -o build/doc/planmgr.info

echo "== stage: build container image =="
docker build -f docker/Dockerfile -t "${REPO}:${VERSION}" .

echo "== stage: push container image =="
docker push "${REPO}:${VERSION}"

echo "== stage: build deb package =="
rm -rf build/deb
mkdir -p build/deb/DEBIAN
mkdir -p build/deb/lib/systemd/system
mkdir -p build/deb/etc/default
mkdir -p build/deb/etc/planmgr
mkdir -p build/deb/usr/share/man/man1
mkdir -p build/deb/usr/share/info

echo "-- staging control files --"
sed "s/^Version:.*/Version: ${VERSION}/" packaging/deb/control > build/deb/DEBIAN/control
cp packaging/deb/conffiles build/deb/DEBIAN/conffiles
cp packaging/deb/postinst build/deb/DEBIAN/postinst
cp packaging/deb/prerm build/deb/DEBIAN/prerm
cp packaging/deb/postrm build/deb/DEBIAN/postrm
chmod 755 build/deb/DEBIAN/postinst build/deb/DEBIAN/prerm build/deb/DEBIAN/postrm

echo "-- staging service unit and configuration templates --"
# NOTE: TLS material (mtls-certs) is deliberately NOT bundled into the deb.
# Certificates and keys are secrets provisioned out-of-band by the operator
# directly into /etc/planmgr/secrets on the target host; the installer never
# carries them. See packaging/deb/postinst, which only verifies their presence.
cp packaging/systemd/planmgr.service build/deb/lib/systemd/system/planmgr.service
cp packaging/etc/default/planmgr build/deb/etc/default/planmgr
cp packaging/etc/planmgr/config.json.template build/deb/etc/planmgr/config.json.template

echo "-- staging rendered documentation --"
gzip -9n -c build/doc/planmgr.1 > build/deb/usr/share/man/man1/planmgr.1.gz
gzip -9n -c build/doc/planmgr.info > build/deb/usr/share/info/planmgr.info.gz

echo "-- building .deb --"
dpkg-deb --build --root-owner-group build/deb "build/planmgr_${VERSION}_all.deb"

echo "== release summary =="
echo "image: ${REPO}:${VERSION}"
echo "deb: build/planmgr_${VERSION}_all.deb"
