pipeline {
  agent { label 'linux' }
  options { timestamps(); disableConcurrentBuilds(); skipDefaultCheckout(true); buildDiscarder(logRotator(numToKeepStr: '15')) }
  stages {
    stage('Checkout Staging') { steps { checkout scm; sh 'test "$BRANCH_NAME" = "Staging"' } }
    stage('Validate source') {
      steps { sh '''#!/usr/bin/env bash
set -euo pipefail
git diff --check
PYTHONPATH=backend python3.11 -m unittest discover -s backend -p 'test_sinvo_*.py' -v
for script in ci/*.sh deploy/rocky/*.sh; do bash -n "$script"; done
''' }
    }
    stage('Create BackOffice artifact') {
      steps { sh '''#!/usr/bin/env bash
set -euo pipefail
mkdir -p artifacts
mkdir -p artifacts/staging-source
git archive --format=tar HEAD backend deploy .python-version | tar -xf - -C artifacts/staging-source
SINVO_BUILD_VERSION="0.1.0+staging.${BUILD_NUMBER}" SINVO_BUILD_REVISION="${GIT_COMMIT}" python3.11 - <<'PYBUILD'
import json,os,pathlib
metadata={"version":os.environ["SINVO_BUILD_VERSION"],"revision":os.environ["SINVO_BUILD_REVISION"]}
pathlib.Path("artifacts/staging-source/backend/.sinvo-build.json").write_text(json.dumps(metadata)+"\\n")
PYBUILD
tar -czf artifacts/backoffice-staging.tar.gz -C artifacts/staging-source backend deploy .python-version
ls -lh artifacts/backoffice-staging.tar.gz
''' }
    }
    stage('Publish to SINVO Update Server') {
      steps {
        withCredentials([string(credentialsId: 'sinvo-publisher-token', variable: 'SINVO_PUBLISH_TOKEN')]) {
          sh '''#!/usr/bin/env bash
set -euo pipefail
set +x
SINVO_RELEASE_NOTES="$(cat RELEASE_NOTES.md)" \
SINVO_RELEASE_VERSION="0.1.0+staging.${BUILD_NUMBER}" python3.11 ci/sinvo-publish.py backoffice artifacts/backoffice-staging.tar.gz "https://dev-updates.sinvo.ge/api/v1/releases/publish/"
'''
        }
      }
    }
  }
  post { always { cleanWs() } }
}
