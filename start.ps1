param(
    [Parameter(Position = 0)]
    [ValidateSet("start", "restart", "big")]
    [string]$Action = "start"
)
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = "C:\Users\Home\AppData\Local\Programs\Python\Python312\python.exe"
$Small = Join-Path $Root "data\models\qwen2.5-1.5b-instruct-q4_k_m.gguf"
$Big = Join-Path $Root "data\models\qwen2.5-7b-instruct-q4_k_m-00001-of-00002.gguf"
$UseBig = $Action -eq "big"
if ($UseBig) { $Action = "start" }
$Model = if ($UseBig) { $Big } else { $Small }
if (-not $UseBig -and -not (Test-Path $Small)) {
    $Url = "https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/qwen2.5-1.5b-instruct-q4_k_m.gguf"
    & curl.exe -L -C - -o $Small $Url
}
if ($Action -eq "restart") {
    Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue |
        ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
}
$Command = "`$env:LLM_MODEL_PATH='$Model'; `$env:PYTHONPATH='src'; Set-Location '$Root'; & '$Python' -m uvicorn api:app --host 127.0.0.1 --port 8000"
Start-Process powershell -ArgumentList "-NoExit", "-Command", $Command
Start-Process "http://127.0.0.1:8000/?v=4"
