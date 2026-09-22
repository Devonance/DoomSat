#!/bin/bash
# Serve Open MCT (openmct-yamcs example, webpack dev server on http://localhost:9000) against the fprime-project instance.
cd "$(dirname "$0")/../external/openmct-yamcs" || exit 1
cp ../../ground/openmct/index.html ../../ground/openmct/index.js example/
exec npx webpack serve --config ./.webpack/webpack.dev.mjs --no-open
