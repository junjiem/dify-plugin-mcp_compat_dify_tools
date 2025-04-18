from typing import Mapping

from dify_plugin import Endpoint
from werkzeug import Request, Response


class McpGetEndpoint(Endpoint):
    def _invoke(self, r: Request, values: Mapping, settings: Mapping) -> Response:
        """
        Streamable HTTP in Dify is a lightweight design,
        it only supported POST and don't support Server-Sent Events (SSE).
        """
        response = {
            "jsonrpc": "2.0",
            "id": None,
            "error": {
                "code": -32000,
                "message": "Not support make use of Server-Sent Events (SSE) to stream multiple server messages."
            },
        }

        return Response(response, status=405, content_type="application/json")
