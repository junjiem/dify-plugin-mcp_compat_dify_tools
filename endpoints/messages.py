import json
import logging
from typing import Mapping, cast, Any

from dify_plugin import Endpoint
from dify_plugin.entities import I18nObject
from dify_plugin.entities.tool import ToolParameter, ToolProviderType, ToolInvokeMessage, ToolDescription
from dify_plugin.interfaces.agent import ToolEntity, AgentToolIdentity
from pydantic import BaseModel
from werkzeug import Request, Response


class EndpointParams(BaseModel):
    tools: list[ToolEntity] | None


class MessageEndpoint(Endpoint):
    def _invoke(self, r: Request, values: Mapping, settings: Mapping) -> Response:
        """
        Invokes the endpoint with the given request.
        """

        session_id = r.args.get('session_id')
        data = r.json
        method = data.get("method")

        print("===============tools==============")
        print(settings.get("tools"))

        if method == "initialize":
            response = {
                "jsonrpc": "2.0",
                "id": data.get("id"),
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {
                        "experimental": {},
                        "prompts": {"listChanged": False},
                        "resources": {
                            "subscribe": False,
                            "listChanged": False
                        },
                        "tools": {"listChanged": False}
                    },
                    "serverInfo": {
                        "name": "MCP Compatible Dify Tools",
                        "version": "1.3.0"
                    }
                }
            }

        elif method == "notifications/initialized":
            return Response("", status=202, content_type="application/json")

        elif method == "tools/list":
            try:
                tools: list[ToolEntity] = self._init_tools(settings.get("tools"))

                mcp_tools = self._init_mcp_tools(tools)

                response = {
                    "jsonrpc": "2.0",
                    "id": data.get("id"),
                    "result": {
                        "tools": mcp_tools
                    }
                }
            except Exception as e:
                response = {
                    "jsonrpc": "2.0",
                    "id": data.get("id"),
                    "error": {
                        "code": -32000,
                        "message": str(e)
                    }
                }
        elif method == "tools/call":
            try:
                tools: list[ToolEntity] = self._init_tools(settings.get("tools"))
                tool_instances = {tool.identity.name: tool for tool in tools} if tools else {}

                tool_name = data.get("params", {}).get("name")
                arguments = data.get("params", {}).get("arguments", {})

                tool_instance = tool_instances.get(tool_name)
                if tool_instance:
                    result = self._invoke_tool(tool_instance, arguments)
                else:
                    raise ValueError(f"Unknown tool: {tool_name}")

                response = {
                    "jsonrpc": "2.0",
                    "id": data.get("id"),
                    "result": {
                        "content": [{"type": "text", "text": result}],
                        "isError": False
                    }
                }
            except Exception as e:
                response = {
                    "jsonrpc": "2.0",
                    "id": data.get("id"),
                    "error": {
                        "code": -32000,
                        "message": str(e)
                    }
                }
        else:
            response = {
                "jsonrpc": "2.0",
                "id": data.get("id"),
                "error": {
                    "code": -32001,
                    "message": f"Unsupported method: {method}"
                }
            }

        self.session.storage.set(session_id, json.dumps(response).encode())
        return Response("", status=202, content_type="application/json")

    def _init_tools(self, tools_param_value) -> list[ToolEntity]:
        """
        init ToolEntity list
        """

        result: list[ToolEntity] = []

        value = cast(list[dict[str, Any]], tools_param_value)
        value = [tool for tool in value if tool.get("enabled", False)]

        for tool in value:
            type = tool["type"]
            tool_name = tool["tool_name"]
            tool_label = tool["tool_label"]
            extra_description = tool.get("extra").get("description", None)
            provider_name = tool["provider_name"]
            schemas = tool.get("schemas", [])
            settings = tool.get("settings", {})

            identity = AgentToolIdentity(
                author="Dify",
                name=tool_name,
                label=I18nObject(en_US=tool_label),
                provider=provider_name,
            )

            llm_description = extra_description if extra_description else tool_label
            description = ToolDescription(
                human=I18nObject(en_US=llm_description),
                llm=llm_description,
            )

            provider_type = ToolProviderType.BUILT_IN
            if type == "api":
                provider_type = ToolProviderType.API
            elif type == "workflow":
                provider_type = ToolProviderType.WORKFLOW

            parameters = []
            for schema in schemas:
                parameters.append(ToolParameter(**schema))

            runtime_parameters = {}
            for parameter_name, parameter_value in settings.items():
                runtime_parameters[parameter_name] = parameter_value.get("value")

            tool_entity = ToolEntity(
                identity=identity,
                parameters=parameters,
                description=description,
                provider_type=provider_type,
                runtime_parameters=runtime_parameters,
            )

            result.append(tool_entity)

        return result

    def _init_mcp_tools(self, tools: list[ToolEntity] | None) -> list[dict]:
        """
        Init mcp tools
        """

        mcp_tools = []
        for tool in tools or []:
            try:
                mcp_tool = self._convert_tool_to_mcp_tool(tool)
            except Exception:
                logging.exception("Failed to convert Dify tool to MCP tool")
                continue

            mcp_tools.append(mcp_tool)

        return mcp_tools

    def _convert_tool_to_mcp_tool(self, tool: ToolEntity) -> dict:
        """
        convert tool to prompt message tool
        """
        mcp_tool = {
            "name": tool.identity.name,
            "description": tool.description.llm if tool.description else "",
            "inputSchema": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }

        parameters = tool.parameters
        for parameter in parameters:
            if parameter.form != ToolParameter.ToolParameterForm.LLM:
                continue

            parameter_type = parameter.type
            if parameter.type in {
                ToolParameter.ToolParameterType.FILE,
                ToolParameter.ToolParameterType.FILES,
            }:
                continue
            enum = []
            if parameter.type == ToolParameter.ToolParameterType.SELECT:
                enum = [option.value for option in parameter.options] if parameter.options else []

            mcp_tool["inputSchema"]["properties"][parameter.name] = {
                "type": parameter_type,
                "description": parameter.llm_description or "",
            }

            if len(enum) > 0:
                mcp_tool["inputSchema"]["properties"][parameter.name]["enum"] = enum

            if parameter.required:
                mcp_tool["inputSchema"]["required"].append(parameter.name)

        return mcp_tool

    def _invoke_tool(self, tool: ToolEntity, tool_call_args) -> str:
        """
        invoke tool
        """

        tool_invoke_responses = self.session.tool.invoke(
            provider_type=ToolProviderType(tool.provider_type),
            provider=tool.identity.provider,
            tool_name=tool.identity.name,
            parameters={**tool.runtime_parameters, **tool_call_args},
        )

        result = ""
        for response in tool_invoke_responses:
            if response.type == ToolInvokeMessage.MessageType.TEXT:
                result += cast(ToolInvokeMessage.TextMessage, response.message).text
            elif response.type == ToolInvokeMessage.MessageType.LINK:
                result += (
                        f"result link: {cast(ToolInvokeMessage.TextMessage, response.message).text}."
                        + " please tell user to check it."
                )
            elif response.type in {
                ToolInvokeMessage.MessageType.IMAGE_LINK,
                ToolInvokeMessage.MessageType.IMAGE,
            }:
                result += f"Not support message type: {response.type}."
            elif response.type == ToolInvokeMessage.MessageType.JSON:
                text = json.dumps(
                    cast(ToolInvokeMessage.JsonMessage, response.message).json_object,
                    ensure_ascii=False,
                )
                result += f"tool response: {text}."
            else:
                result += f"tool response: {response.message!r}."

        return result
