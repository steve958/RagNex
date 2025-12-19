param(
  [Parameter(Mandatory = $false)]
  [string]$TenantId,

  [Parameter(Mandatory = $false)]
  [switch]$DeleteLegacy
)

$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $PSScriptRoot
$venvPy = Join-Path $repoRoot '.venv\Scripts\python.exe'

if (!(Test-Path $venvPy)) {
  throw "Could not find venv python at $venvPy"
}

$code = @'
import argparse
import uuid

from backend.app.services.opensearch_migrations import OpenSearchMigrationService

p = argparse.ArgumentParser()
p.add_argument('--tenant-id', default=None)
p.add_argument('--delete-legacy', action='store_true')
args = p.parse_args()

svc = OpenSearchMigrationService()
svc.ensure_policies_and_templates()

if args.tenant_id:
    tid = uuid.UUID(args.tenant_id)
    svc.migrate_legacy_tenant_index(tid, delete_legacy=args.delete_legacy)
'@

$pyArgs = @()
if ($TenantId) { $pyArgs += @('--tenant-id', $TenantId) }
if ($DeleteLegacy) { $pyArgs += @('--delete-legacy') }

& $venvPy -c $code @pyArgs
