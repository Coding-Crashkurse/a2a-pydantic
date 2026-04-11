param(
    [string]$SchemaUrl = "https://a2a-protocol.org/latest/spec/a2a.json"
)
$ErrorActionPreference = "Stop"
$Build = ".build"

# Ensure build directory exists (keep existing files like a2a_03.json untouched)
if (-not (Test-Path $Build)) {
    New-Item -ItemType Directory -Path $Build | Out-Null
}

# Download schema
$SchemaRaw = Join-Path $Build "a2a_raw.json"
$SchemaResolved = Join-Path $Build "a2a.json"
Write-Host "Downloading schema from $SchemaUrl ..."
Invoke-WebRequest -Uri $SchemaUrl -OutFile $SchemaRaw

# Resolve external $refs, strip proto artifacts, normalize definition names
Write-Host "Resolving external `$ref pointers ..."
python scripts\resolve_refs.py $SchemaRaw $SchemaResolved

# Generate models
$OutputFile = "src\a2a_pydantic\v10\models.py"
$OutputDir = Split-Path $OutputFile -Parent
if (-not (Test-Path $OutputDir)) {
    New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null
}

Write-Host "Generating models -> $OutputFile ..."
python -m datamodel_code_generator `
    --input $SchemaResolved `
    --input-file-type jsonschema `
    --output $OutputFile `
    --output-model-type pydantic_v2.BaseModel `
    --use-schema-description `
    --use-field-description `
    --snake-case-field `
    --no-alias `
    --set-default-enum-member `
    --base-class a2a_pydantic.base.A2ABaseModel `
    --target-python-version 3.10 `
    --formatters black --formatters isort

Write-Host "Done. Output: $OutputFile"
