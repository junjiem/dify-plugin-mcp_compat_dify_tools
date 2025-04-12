import uuid
import time
import json
from typing import Mapping
from werkzeug import Request, Response
from dify_plugin import Endpoint


def create_sse_message(event, data):
    return f"event: {event}\ndata: {json.dumps(data) if isinstance(data, (dict, list)) else data}\n\n"


class SSEEndpoint(Endpoint):
    def _invoke(self, r: Request, values: Mapping, settings: Mapping) -> Response:
        """
        Invokes the endpoint with the given request.
        """
        session_id = str(uuid.uuid4()).replace("-", "")

        def generate():
            endpoint = f"messages/?session_id={session_id}"
            yield create_sse_message("endpoint", endpoint)

            while True:
                message = None
                try:
                    message = self.session.storage.get(session_id)
                except:
                    pass
                if message is None:
                    time.sleep(0.5)
                    continue
                message = message.decode()
                self.session.storage.delete(session_id)
                yield create_sse_message("message", message)

        return Response(generate(), status=200, content_type='text/event-stream')
