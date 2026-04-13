"""Template registry for EIA document types.

Maps document_type strings (e.g. "EA", "EAF", "CE") to template classes that
define section structure, LLM prompts, and static renderers for each document
format.
"""

from abc import ABC, abstractmethod


class BaseTemplate(ABC):
    """Interface that every document template must implement."""

    document_type: str  # "EA", "EAF", "CE", etc.

    @property
    @abstractmethod
    def sections(self) -> list[dict]:
        """Ordered list of section definitions.

        Each dict: {"id": str, "title": str, "requires_llm": bool}
        """

    @abstractmethod
    def get_section_data(self, section_id: str, state: dict) -> dict:
        """Extract the relevant subset of pipeline state for this section."""

    @abstractmethod
    def get_section_prompt(self, section_id: str, section_data: dict) -> str:
        """Build the LLM user prompt for a narrative section.

        Only called when the section's ``requires_llm`` is True.
        """

    @abstractmethod
    def render_static_section(self, section_id: str, section_data: dict) -> str:
        """Render a section that needs no LLM (tables, metadata, lists).

        Only called when the section's ``requires_llm`` is False.
        """


class TemplateRegistry:
    """Maps document_type → template class."""

    _templates: dict[str, type[BaseTemplate]] = {}

    @classmethod
    def register(cls, document_type: str):
        """Decorator that registers a template class for a document type."""
        def decorator(template_class: type[BaseTemplate]):
            cls._templates[document_type] = template_class
            return template_class
        return decorator

    @classmethod
    def get_template(cls, document_type: str) -> BaseTemplate:
        template_class = cls._templates.get(document_type)
        if template_class is None:
            raise ValueError(
                f"No template registered for document type: {document_type}"
            )
        return template_class()

    @classmethod
    def available_types(cls) -> list[str]:
        return list(cls._templates.keys())
