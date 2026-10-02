pipeline {
    agent any
    options { timestamps(); disableConcurrentBuilds(); timeout(time: 75, unit: 'MINUTES'); buildDiscarder(logRotator(numToKeepStr: '15')) }
    parameters {
        string(name: 'TARGET_HOST', defaultValue: '10.0.110.151', description: 'Rocky Linux 9 ERP server')
        choice(name: 'DB_ENGINE', choices: ['postgres', 'mysql', 'mssql'], description: 'PostgreSQL is installed automatically for a fresh server; other engines require backend.env configuration')
        string(name: 'HTTP_ALLOWED_CIDRS', defaultValue: '10.0.0.0/8', description: 'Comma-separated private networks allowed to reach the HTTP pilot')
    }
    stages {
        stage('Check source') {
            steps {
                sh '''#!/usr/bin/env bash
set -euo pipefail
git diff --check
for script in ci/*.sh deploy/rocky/*.sh; do bash -n "$script"; done
for command in bash git ssh scp ssh-keygen tar sha256sum; do command -v "$command" >/dev/null || { echo "Missing Jenkins agent command: $command" >&2; exit 1; }; done
'''
            }
        }
        stage('Archive revision') {
            steps {
                sh '''#!/usr/bin/env bash
set -euo pipefail
mkdir -p artifacts
revision=$(git rev-parse HEAD)
git archive --format=tar.gz --output="artifacts/$revision.tar.gz" HEAD backend deploy .python-version
(cd artifacts && sha256sum "$revision.tar.gz" > "$revision.sha256")
'''
                archiveArtifacts artifacts: 'artifacts/*.tar.gz,artifacts/*.sha256', fingerprint: true
            }
        }
        stage('Install, test and deploy ERP') {
            when {
                expression { !env.CHANGE_ID && (env.BRANCH_NAME == 'Production' || env.GIT_BRANCH == 'origin/Production' || env.GIT_BRANCH == 'Production') }
            }
            steps {
                withCredentials([usernamePassword(credentialsId: 'pos_server_creds', usernameVariable: 'POS_SSH_USER', passwordVariable: 'POS_SSH_PASSWORD')]) {
                    sh(label: 'Deploy on Rocky Linux', script: 'bash ci/deploy.sh')
                }
            }
        }
    }
    post {
        success { echo 'For a successful Production deployment: http://10.0.110.151/admin/ . Initial login instructions are in docs/deployment.md.' }
        failure { echo 'Deployment did not complete. Check the failed stage; do not reset the database or POS queues.' }
    }
}
