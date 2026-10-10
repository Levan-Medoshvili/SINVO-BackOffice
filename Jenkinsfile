pipeline {
  agent { label 'linux' }
  options { timestamps(); disableConcurrentBuilds(); skipDefaultCheckout(true); buildDiscarder(logRotator(numToKeepStr: '15')) }
  stages {
    stage('Checkout Staging') { steps { checkout scm; sh 'test "$BRANCH_NAME" = "Staging"' } }
    stage('Validate source') {
      steps { sh '''#!/usr/bin/env bash
set -euo pipefail
git diff --check
for script in ci/*.sh deploy/rocky/*.sh; do bash -n "$script"; done
''' }
    }
    stage('Create BackOffice artifact') {
      steps { sh '''#!/usr/bin/env bash
set -euo pipefail
mkdir -p artifacts
git archive --format=tar.gz -o artifacts/backoffice-staging.tar.gz HEAD backend deploy .python-version
ls -lh artifacts/backoffice-staging.tar.gz
''' }
    }
    stage('Publish to SINVO Update Server') {
      steps {
        withCredentials([string(credentialsId: 'sinvo-publisher-token', variable: 'SINVO_PUBLISH_TOKEN')]) {
          sh '''#!/usr/bin/env bash
set -euo pipefail
set +x
SINVO_PUBLISH_DEBUG=1 SINVO_RELEASE_VERSION="0.1.0+staging.${BUILD_NUMBER}" python3.11 ci/sinvo-publish.py backoffice artifacts/backoffice-staging.tar.gz "https://updates.sinvo.ge/api/v1/releases/publish/"
'''
        }
      }
    }
  }
  post { always { cleanWs() } }
}
