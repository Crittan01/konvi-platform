# Entendiendo MCP y Skills en Antigravity
**MCP (Model Context Protocol)**: Un estándar para proporcionar contexto de forma controlada a asistentes de IA desde fuentes externas (archivos locales, herramientas, bases de datos, APIs).

**Skills en Antigravity**: Carpetas con instrucciones, scripts o contexto almacenados usualmente en `.agents/skills`. Estos configuran capacidades extendidas, como rutinas complejas o manejo de stacks específicos. Se activan/apoyan leyendo los MD locales (ej. `SKILL.md`).

**Gemini Docs MCP**: Proveedor MCP que permite buscar y añadir contexto oficial en tiempo de conversación, reduciendo alucinaciones al preguntar "¿Cómo implemento X en Supabase?". 

Debes comprobar en el chat y el entorno si están configurados antes de utilizarlos activamente. Un fallback es buscar en la web vía \`search_web\`.\n