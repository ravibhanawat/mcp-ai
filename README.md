# SAP AI Agent — MCP Server

A Python-based AI agent and **MCP (Model Context Protocol) server** that exposes **30 SAP tools** across all major ERP modules (FI/CO, MM, SD, HR, PP, ABAP) — usable directly from **Claude Desktop**, **Cursor**, or any MCP-compatible client.

No SAP license required — runs fully in demo/mock mode out of the box.

---

## Architecture

```
sap_ai_agent/
├── mcp_server.py            ← MCP server (stdio) — entry point for Claude/Cursor
├── mcp_client.py            ← MCP client utilities
├── main.py                  ← CLI entry point
├── api_server.py            ← REST API (FastAPI)
├── config_manager.py        ← Config loader
├── audit_logger.py          ← Audit logging
│
├── agent/
│   └── sap_agent.py         ← Core AI Agent (Ollama integration)
│
├── tools/
│   └── tool_registry.py     ← 30 SAP tools mapped to functions
│
├── modules/
│   ├── fi_co.py             ← FI/CO: Finance & Controlling
│   ├── mm.py                ← MM: Materials Management
│   ├── sd.py                ← SD: Sales & Distribution
│   ├── hr.py                ← HR: Human Resources
│   ├── pp.py                ← PP: Production Planning
│   └── abap.py              ← ABAP: Custom development tools
│
├── auth/
│   ├── jwt_handler.py       ← JWT authentication
│   ├── rbac.py              ← Role-based access control
│   └── users.py             ← User management
│
└── mock_data/
    └── sap_data.py          ← Demo SAP data (vendors, materials, etc.)
```

---

## Quick Start

### 1. Clone & Install
```bash
git clone https://github.com/ravibhanawat/mcp-ai.git
cd mcp-ai
pip install -r requirements.txt
```

### 2. Configure
```bash
cp config.json.example config.json
cp users.json.example users.json
```

### 3. Use as MCP Server (Claude Desktop / Cursor)

```bash
python mcp_server.py
```

Add to your Claude Desktop `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "sap-ai-agent": {
      "command": "python",
      "args": ["/path/to/mcp-ai/mcp_server.py"]
    }
  }
}
```

### 4. Use as CLI (requires Ollama)
```bash
# Install & start Ollama
curl -fsSL https://ollama.ai/install.sh | sh
ollama pull llama3.2
ollama serve

# Run
python main.py
python main.py --model mistral
```

### 5. Use as REST API
```bash
uvicorn api_server:app --reload --port 8000
```

---

## MCP Tools (30 total)

| Module | Example Tools |
|--------|---------------|
| **FI/CO** | Get invoice, list invoices, get vendor, get cost center, budget vs actual |
| **MM** | Check stock, get material, get PO, list POs, reorder alerts |
| **SD** | Get sales order, list orders, customer orders, create order, delivery status |
| **HR** | Leave balance, payslip, apply leave, search employees, org chart |
| **PP** | Get production order, BOM, list orders, create order, work center capacity |
| **ABAP** | Custom ABAP tool integrations |

---

## Example Queries

### FI/CO (Finance)
```
> What is the status of invoice INV1000?
> Show me all open invoices
> What is the budget vs actual for cost center CC100?
> List all cost centers
> Get vendor details for V001
```

### MM (Materials Management)
```
> Check stock level for material MAT001
> Show purchase order PO2001
> Which materials need reordering?
> List all open purchase orders
> Get material info for MAT003
```

### SD (Sales & Distribution)
```
> Show all open sales orders
> Get details for sales order SO5001
> Show all orders for customer C001
> Create a sales order for customer C002, material MAT001, quantity 10
> What is the delivery status of DEL6001?
```

### HR (Human Resources)
```
> What is the leave balance for employee EMP001?
> Show Ravi Sharma's payslip
> Apply 3 days annual leave for EMP001
> Search employees in IT department
> Show org chart for EMP001
```

### PP (Production Planning)
```
> Show production order PRD7001
> What is the BOM for MAT001?
> List all in-progress production orders
> Create a production order for MAT002, quantity 50
> Show work center capacity utilization
```

---

## 🔧 SAP Reference IDs

| Type | IDs |
|------|-----|
| Vendors | V001 (TCS), V002 (Infosys), V003 (SAP AG) |
| Materials | MAT001 (Laptop), MAT002 (Chair), MAT003 (Steel), MAT004 (Paper) |
| Customers | C001 (Reliance), C002 (Wipro), C003 (HDFC) |
| Employees | EMP001 (Ravi Sharma), EMP002 (Priya Singh), EMP003 (Amit Patel) |
| Cost Centers | CC100 (IT), CC200 (HR), CC300 (Sales) |
| Invoices | INV1000, INV1001, INV1002 |
| Sales Orders | SO5001, SO5002, SO5003 |
| Prod Orders | PRD7001, PRD7002, PRD7003 |

---

## 🌐 REST API Endpoints

When running `api_server.py`:

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | API info |
| GET | `/health` | Ollama connection status |
| POST | `/chat` | Send a message |
| POST | `/reset` | Clear conversation |
| GET | `/tools` | List all 25 SAP tools |
| GET | `/modules` | List tools by module |

### Chat API Example
```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Check stock for MAT001"}'
```

---

## 🔌 Connecting to Real SAP

To connect to a real SAP system, replace mock functions in `modules/` with:

**RFC/BAPI (on-premise SAP):**
```bash
pip install pyrfc
```
```python
import pyrfc
conn = pyrfc.Connection(ashost='your-sap-host', sysnr='00', client='100', user='user', passwd='pass')
result = conn.call('BAPI_MATERIAL_GET_DETAIL', MATERIAL='MAT001')
```

**SAP S/4HANA Cloud (OData API):**
```bash
pip install requests
```
```python
import requests
url = "https://your-tenant.s4hana.cloud.sap/sap/opu/odata/sap/API_MATERIAL_DOCUMENT_SRV"
r = requests.get(url, auth=('user', 'pass'))
```

---

## 🤖 Supported Ollama Models

| Model | Size | Quality | Speed |
|-------|------|---------|-------|
| llama3.2 | 2GB | ★★★★☆ | Fast |
| mistral | 4GB | ★★★★★ | Medium |
| llama3.1:8b | 5GB | ★★★★★ | Medium |
| gemma2 | 5GB | ★★★★☆ | Medium |
| codellama | 4GB | ★★★☆☆ | Fast |

---

## Requirements

- Python 3.10+
- [Ollama](https://ollama.ai) (only needed for CLI/agent mode)
- 4GB+ RAM (8GB recommended for larger models)

---

## License

MIT — see [LICENSE](LICENSE)
