# Bitácora de IA

## Herramientas
- **Claude** (Anthropic), en la interfaz de chat con ejecución de código: diseñó la estructura, escribió el código, las pruebas, el README y la bitácora, y ejecutó todo en su entorno.
- Nada de pago, ninguna llave de API. No se usó ningún LLM *dentro* del producto (el campo `mensaje` se lee con palabras clave).
- Mis revisiones y decisiones propias: [COMPLETAR: qué cambié, qué rechacé, qué decidí distinto a lo que propuso la IA].

## Prompts clave
1. **Prompt inicial** (el correo completo con contexto, qué construir, reglas de calificación, datos, entregables y reglas) más el archivo `leads_test_darhe.csv`, con la instrucción "REALIZA ESTO".
2. [COMPLETAR con los prompts reales que uses después, por ejemplo: pedir un ajuste a una decisión de calificación, pedir que explique el módulo de duplicados para prepararte para la entrevista, etc. Solo incluye los que sí enviaste.]

## Una cosa que la IA hizo mal y cómo la detecté
**Regla de teléfonos demasiado agresiva.** Al escribir la validación, la IA marcó como inválido cualquier número con **dos dígitos distintos o menos** (para atrapar basura tipo `0000000000`). Pasó sus propias pruebas y los 15 leads del test, porque ahí ningún número real caía en eso. Lo detectó al probar el webhook con un número inventado, `55 4444 5555`: el lead salió "Descartado, sin forma de contacto" aunque traía un correo válido, y el duplicado que debía unirse por teléfono no se unió. La causa era mi regla, no el dato. Se relajó a "todos los dígitos iguales" y se agregó una prueba (`55 4444 5555` debe ser válido) para que no vuelva a pasar.
Lección: una regla "defensiva" puede descartar leads reales; descartar por error cuesta más que dejar pasar un dato dudoso.

Otros fallos menores que se atraparon al correr el código: un `mkdir` con llaves que creó una carpeta literal `{leadflow,tests,...}` (lo vi en el `ls`), y una expresión regular de "S.A. de C.V." que dejaba un punto sobrante (la vi en una prueba rápida). [COMPLETAR/VERIFICAR: confirma tú estos puntos al revisar el repo.]
