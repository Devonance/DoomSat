#!/bin/bash
# Serve Open MCT (openmct-yamcs example, webpack dev server on http://localhost:9000) against the fprime-project instance.
# Requires external/openmct-yamcs with node_modules and an Open MCT build in node_modules/openmct (see README).
cd "$(dirname "$0")/../external/openmct-yamcs" || exit 1
cp ../../ground/openmct/index.html ../../ground/openmct/index.js example/
# The stock dev config proxies to 0.0.0.0 (not dialable on Windows) and shows an error overlay for the
# example display's missing telemetry; both patched in place.
sed -i 's#http://0.0.0.0:8090/#http://localhost:8090/#; s#ws://0.0.0.0:8090/api/websocket#ws://localhost:8090/api/websocket#' .webpack/webpack.dev.mjs
grep -q "overlay: false" .webpack/webpack.dev.mjs || sed -i 's#  devServer: {#  devServer: {\n    client: { overlay: false },#' .webpack/webpack.dev.mjs
exec npx webpack serve --config ./.webpack/webpack.dev.mjs --no-open
