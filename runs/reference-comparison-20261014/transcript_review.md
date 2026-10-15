# Nuevas referencias inglesas: revisión literal

La configuración predeterminada `config/local.json` apunta a `/home/siamarino/audios/04_referencia_ingles_emocion.wav`. Su texto `references/reference_b.txt` empieza «okay so uh we have this kind of dogs...». La grabación actual empieza «Okay, so good night everyone...» y habla de Resident Evil 4: ese texto viejo ya no corresponde. `04_referencia_ingles.wav` tampoco usa ese texto; comienza «Good night, everyone...».

Los archivos `.txt` junto a las copias WAV conservan las palabras, muletillas, repeticiones y gramática que dio la transcripción automática. Solo añadí puntuación. Los siguientes puntos siguen dudosos; verificar escuchando el tramo indicado antes de usar estas parejas en producción:

| Referencia | Tiempo | Texto usado en el `.txt` | Duda observada |
| --- | --- | --- | --- |
| Tranquila | 1,2–1,8 s | **Good** night | Probabilidad de Whisper 0,65; ambas escuchas automáticas coinciden. |
| Tranquila | 6,3–7,2 s | **Resident Evil** 4 Remake | Whisper completo oyó «Rusted and Evil»; el recorte oyó «Rusty Renewable». El nombre escrito es una inferencia contextual que requiere escuchar. |
| Tranquila | 9,3–12 s | at a **pretty relaxed and chill gameplay** | Gramática poco natural, conservada tal como la devolvió Whisper. Verificar palabras exactas. |
| Tranquila | 47,6–50,7 s | **Um, yeah, yeah, I'll think I'll go with it** | Las muletillas tuvieron probabilidad baja; se conservó la repetición y el orden de palabras del ASR completo. |
| Emotiva | 0–2,4 s | **Okay, so good night** everyone | Probabilidades individuales 0,42–0,59; las dos transcripciones coinciden. |
| Emotiva | 36–42 s | **this could be a good video to upload** to YouTube | El audio completo dio esa lectura; un recorte dio «it's cool be a good video to apply». Revisar literalmente. |

Los JSON `tranquila_asr.json`, `emotiva_asr.json` y los de recortes conservan tiempos y probabilidades por palabra. Los WAV de recortes permiten escuchar las dudas. Ninguna de estas dudas se dio por aprobada automáticamente.
