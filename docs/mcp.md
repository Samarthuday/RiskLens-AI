# Optional MCP server

Install the optional MCP dependency and start the app's local SQLite demo first:

```bash
python -m pip install -e '.[mcp]'
python -m app.mcp_server
```

The server uses MCP stdio transport. Copy [examples/mcp-config.json](../examples/mcp-config.json) into a compatible client's configuration and replace both absolute paths. The server exposes typed, read-only tools: `get_transaction`, `get_account_history`, `get_transaction_velocity`, `get_model_prediction`, and `evaluate_risk_policy`.

Tools expose only predefined queries and outputs. Transaction descriptions are excluded, no arbitrary SQL or filesystem access is available, and a risk prediction returns unavailable when the trusted research artifact is absent. The MCP process runs locally with the same SQLite data and artifact path as the API; do not point it at real customer data for this portfolio demo.
