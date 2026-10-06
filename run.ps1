Set-Location $PSScriptRoot
.\venv\Scripts\Activate.ps1

# ---- Configuration ----
$env:PYTHONIOENCODING = "utf-8"
$env:OLLAMA_MODEL = "llama3.2"
$env:POLL_SECONDS = "30"
$env:DRY_RUN = "false"                      # change to "false" to really send
$env:ALLOWED_DOMAINS = "@gmail.com, @tcs.com"
$env:MAX_REPLIES_PER_SENDER_PER_DAY = "3"
$env:SYSTEM_PROMPT = "You are an email assistant for Abhijit. Reply concisely and politely. Business hours are Mon-Fri 10am-6pm IST. Never promise prices, dates or meetings. If unsure, say Abhijit will follow up personally. Output only the reply body."
$env:SIGNATURE = "`n`n-- `nAutomated reply. Abhijit will follow up if needed."
# -----------------------

# Restart automatically if the script crashes
while ($true) {
    python gmail_auto_reply.py *>> agent.log
    Start-Sleep -Seconds 15
}