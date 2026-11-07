# Dayforce background notes

Gathered from web searches on Nov 5, 2026, before the task was known. **Confirm everything against the task instructions.** The task may not use the Dayforce API at all (it could be plain Python, data processing or SQL).

## What Dayforce is

HR, payroll and workforce management software with a REST API.

## Sources

- Dayforce Development Network (DDN): https://developers.dayforce.com (registration required). Named as the primary API resource in the [Dayforce REST API FAQ](https://devcommunity.dayforce.com/getting-started-support-40/dayforce-rest-api-faq-107).
- Dayforce community: https://devcommunity.dayforce.com
- Client namespace explanation: https://docs.leena.ai/docs/dayforce

## Key points

- **Client namespace / company ID:** a short tenant name that appears in API URLs as `.../api/{clientName}/...`. The Dayforce admin or employer provides it; you cannot generate it.
- **OAuth token endpoints differ per environment.** Examples seen in community posts:
  - Production: `https://dfid.dayforcehcm.com/connect/token`
  - Non-production: `https://dfidconfig.np.dayforcehcm.com/connect/token`
- Some integrations use an API username and password or a custom header token instead of OAuth. Use whatever the task specifies.
- Credentials always go in `.env`, never in code.

## Example call pattern (placeholders, adjust to the task)

```python
import requests
from dayforce_task.config import get_setting

base = get_setting("DAYFORCE_BASE_URL")
client = get_setting("DAYFORCE_CLIENT")
resp = requests.get(
    f"{base}/api/{client}/...",
    headers={"Authorization": f"Bearer {get_setting('DAYFORCE_TOKEN')}"},
    timeout=30,
)
resp.raise_for_status()
data = resp.json()
```

## Unknown until the task arrives

Which endpoints, which environment, how to authenticate, input data format, and how to submit results.

## SDKs and client libraries (checked Nov 5, 2026)

**No official Dayforce SDK was found** in web searches. The main developer resource is the REST API documented on the Dayforce Development Network. Dayforce does not appear to publish a Python package of its own. Only the unofficial options below turned up, and none of them has been installed or tested.

| Library | What it is | Notes |
|---------|------------|-------|
| [dayforcepy](https://pypi.org/project/dayforcepy) (`pip install dayforcepy`) | Python connector for the Dayforce HCM API | Resource classes for employees, departments, job assignments, and employee properties, plus a `ReportFactory` for reports returned as pandas DataFrames. Takes a username, password, environment (test or production), and company ID. Appears to be community-made; first published around July 2025. |
| [dayforce-client](https://pypi.org/project/dayforce-client/) / [GitHub](https://github.com/goodeggs/dayforce-client) | Python SDK for the Dayforce REST API and SFTP server | From Good Eggs, a third party. Older (around 2022), so it may not be maintained. |
| [tap-dayforce](https://github.com/goodeggs/tap-dayforce) | Singer tap that extracts data from the Dayforce REST API v1 | Data-pipeline tool, not a general client. |
| [dlt Dayforce source](https://dlthub.com/context/source/dayforce-employee-information) | Loads Dayforce data using the `dlt` library | Lists the base URL as `https://www.dayforcehcm.com/api/{clientName}/v1` with a Bearer token in the `Authorization` header. |
| [Ballerina connector](https://github.com/ballerina-platform/module-ballerinax-dayforce), [PHP client](https://github.com/FBCLIT/DayforceApi), [PowerShell module](https://github.com/darrenjrobinson/Dayforce) | Other languages | Not relevant for Python. |

No public OpenAPI/Swagger file for Dayforce turned up. If the task provides one, a client can be generated with `openapi-python-client`.

### Recommendation

- Use `requests` (already installed) unless the task names a specific library. It works with any authentication method and avoids depending on an unofficial package.
- Treat third-party packages as optional helpers. Check their license, last release date, and compatibility with Python 3.14 and 3.12 before relying on them, and install in both environments.
- If the task provides its own client or SDK, use that.

## MCP servers (checked Nov 5, 2026)

**No official Dayforce MCP server was found** in web searches. Dayforce documentation lives on the Dayforce Development Network (registration required) and the Dayforce Help Portal. No documentation-assistant MCP from Dayforce turned up. (Salesforce does publish docs MCP servers, but that is a different company.)

Third-party MCP servers that expose Dayforce exist. None has been installed or configured here.

| Provider | What it offers | Notes |
|----------|----------------|-------|
| [Apideck](https://www.apideck.com/mcp-server/ceridian-dayforce) | Managed MCP server for Dayforce HRIS data | Lists 2 resources. Data goes through Apideck's service. |
| [Zapier](https://zapier.com/mcp/dayforce) | Dayforce actions exposed to MCP-capable AI tools | Runs through a Zapier account. |
| [Stacksync](https://www.stacksync.com/integrations/airtable-and-ceridian-dayforce) | Sync workflows between Dayforce and other apps | Integration product, not a developer-docs tool. |

These tools act on live Dayforce data. They do not teach the API. Connecting one sends HR or payroll data through a third party, so do not use them for a job test unless the task allows it. If one is ever configured, put it in `.kiro/settings/mcp.json` and never store credentials in that file.

Better sources for guidance while building: the DDN documentation, the [Dayforce community](https://devcommunity.dayforce.com), and the task's own instructions.
