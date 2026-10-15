# Comparación de las dos grabaciones nuevas

`config/local.json` sigue seleccionando `/home/siamarino/audios/04_referencia_ingles_emocion.wav` y `references/reference_b.txt`; la transcripción vieja menciona perros e iglesia y no corresponde a ninguna grabación nueva. Los originales no se editaron.

## Referencias y textos provisionales

| Opción | WAV copiado | Texto correspondiente | Configuración local |
| --- | --- | --- | --- |
| Tranquila (57,58 s) | `/home/siamarino/audios/referencia_ingles_nueva_voz_tranquila_20261014.wav` | `/home/siamarino/audios/referencia_ingles_nueva_voz_tranquila_20261014.txt` | `config/reference_tranquila.local.json` |
| Emotiva (47,97 s) | `/home/siamarino/audios/referencia_ingles_nueva_voz_emotiva_20261014.wav` | `/home/siamarino/audios/referencia_ingles_nueva_voz_emotiva_20261014.txt` | `config/reference_emotiva.local.json` |

Ver `transcript_review.md` para las palabras que requieren escucha. Cada configuración solo cambia el bloque `reference` de `config/local.json`, con SHA-256 esperado del texto respectivo. La referencia predeterminada permanece igual. Para elegir una pareja como predeterminada, revisar primero las palabras dudosas.

## Prueba A/B nueva

Frases exactas en `prompts.json`, semillas 5101, 5102 y 5103 por orden. Se generaron con Qwen English ICL, la misma revisión/modelo/ajustes, cada vez desde su WAV y texto nuevos. El comando de prueba llama directamente al generador del checkout y no consulta la caché de los jobs. Los manifiestos en `tranquila_takes/` y `emotiva_takes/` registran hashes, ajustes, tiempos y salidas.

Escucha recomendada: `comparacion_alternada_tranquila_emotiva.wav`. Orden: frase 1 tranquila, frase 1 emotiva, frase 2 tranquila, frase 2 emotiva, frase 3 tranquila, frase 3 emotiva. También están `tranquila_3_frases.wav` y `emotiva_3_frases.wav`. Las tomas individuales están en `tranquila_takes/` y `emotiva_takes/`.

Whisper reconoció las tres frases completas en ambos montajes (`tranquila_takes_asr.json`, `emotiva_takes_asr.json`). Eso comprueba cobertura textual aproximada, no identidad de voz ni aprobación auditiva.
