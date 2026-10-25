# Use the Vercel website with Ollama on your computer

The hosted app already supports this path:

`Vercel website in your browser → Ollama at http://127.0.0.1:11434`

The browser sends the prepared household context to your local model. The
Vercel backend prepares and validates the answer; it does not connect to your
computer's localhost. Open the website on the same computer running Ollama.

## Windows setup

1. Quit Ollama from the system tray so the existing server releases port 11434.
2. In PowerShell, allow the exact website origin and start Ollama:

   ```powershell
   $env:OLLAMA_ORIGINS = 'https://wattsnext.vercel.app'
   ollama serve
   ```

   Leave that terminal running. If your deployment uses a different hostname,
   replace the URL with that site's origin, without a trailing slash or path.
   Settings shows the command for the website you are currently using.
3. Open another terminal and run `ollama list` to see installed model names.
4. Open the Vercel website, then Settings / Choose AI connection. Select
   **Local · Ollama**, switch **Use household facts without AI** off, set
   the address to `http://127.0.0.1:11434`, and enter an installed model name.
5. Click **Connect & save**. Allow the site's local-device / local-network
   permission if the browser asks. If previously denied, update that permission
   in the browser's site settings and retry.

The `OLLAMA_ORIGINS` setting must apply to the running Ollama server, not just a
new terminal while an older server remains active. For persistent Windows app
configuration, add the same value as a user environment variable, then quit
and restart the Ollama application.

Ollama can stay bound to localhost. No public tunnel, router forwarding, or
LAN-hosted app server is needed for this browser connection. A browser on a
different computer would connect to that computer's localhost instead.

References: [Ollama configuration](https://docs.ollama.com/faq) and
[browser local-network access](https://developer.mozilla.org/en-US/docs/Web/Security/Defenses/Local_network_access).
