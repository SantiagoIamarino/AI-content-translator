# Plan de desarrollo acordado — doblaje ES→EN

Versión 2, 2026-10-17. Reemplaza la versión 1 de este archivo; sus
diferencias están en Git. Diagnóstico de respaldo:
[frontier-review-report-20261017.md](frontier-review-report-20261017.md).
Explicación simple del pipeline: [pipeline-explicado.md](pipeline-explicado.md).

## Resumen para vos

- **Meta:** que se pierdan la menor cantidad posible de frases, que el
  programa nunca se quede parado de noche, y que los finales de voz no hagan
  descartar tomas buenas.
- **Cómo:**
  - se dejan de frenar frases por diferencias menores entre escuchas;
  - el "árbitro" de las dudas pasa a ser un Whisper grande (que escucha), en
    lugar de Luna (que solo lee);
  - las correcciones sin confirmar igual se doblan;
  - el supervisor reintenta en vez de rendirse.
- **Se hace en 6 corridas cortas con pruebas en el medio.** Vos escuchás en dos
  puntos: después de recuperar el video del 16 y después de la prueba de
  10–15 minutos.

## 1. Decisiones tomadas

| Tema | Decisión |
|---|---|
| Frases dudosas | **Política permisiva:** se dobla casi todo. Solo se omite una frase **corta** con una diferencia **grave** (negación o número) que el árbitro no pueda resolver. |
| Frase larga con una duda grave | Se dobla con la lectura que gane la votación de las escuchas (ver E2). En gameplays nuevos, con frases más cortas, se pierde solo el pedacito dudoso (E8). |
| Corrección sin confirmar en la última ronda | **Se dobla** la última versión corregida y se informa como "sin confirmar". |
| Respuesta del revisor rechazada o agotada | Se dobla la traducción disponible (borrador o última versión válida) y se informa. |
| Revisor | Luna con razonamiento **high** solo para el rol de revisión; los demás roles siguen en `medium`. Mismo proveedor, autenticación ChatGPT, sin fallback a API. |
| Resolución de fuente con Luna (bucle actual) | **Se retira** del camino normal; la reemplazan el árbitro acústico y la revisión normal. |
| Árbitro acústico | **Whisper large-v3** (descarga autorizada, ~2,9 GB). Se usa como segunda escucha independiente y árbitro de dudas. No reemplaza a Qwen: la voz no cambia. |
| Finales de voz | Priorizar **no descartar** tomas aprobadas (orden en E3). |
| Huella del video | Se quita el cálculo completo al retomar; queda un chequeo de tamaño y fecha. |
| "Parcial" / "completo" | Se reemplaza por porcentaje de cobertura y lista de faltantes. Las zonas ininteligibles se informan pero no impiden "completo". |
| Tomas por frase | Se mantienen **4 válidas + 4 extra**. |
| Paralelizar la voz | Prueba de medición; se implementa ahora solo si acelera ≥ 1,7× y las tomas pasan los mismos controles. |
| Proveedor caído | **Nunca detenerse:** reintentos con esperas crecientes durante toda la noche; al vencer un plazo, exportar lo que haya, marcado como falla del servicio. |
| Escucha humana | Solo durante el desarrollo, como feedback tuyo. Los jobs normales corren sin intervención. |
| Gold set (hoja de respuestas) | **No se hace.** Lo reemplazan Whisper grande como corrector automático y tu escucha de las pruebas. |
| Prueba intermedia | Fragmento de **10–15 min** de una grabación nueva y variada, más una corrida final de 1–2 h. |

**Se conserva sin cambios:**
- Qwen 1.7B con ICL en inglés, la referencia tranquila aprobada y sus hashes, y los ajustes de generación;
- recorte RMS 0,005 / 10 ms / pad 0 y tempo máximo 1,10;
- game bed intacto, picture copiado y comparación española apagada;
- anclas de reacciones y muletillas y pausas.

**Futuro cercano (fuera de este plan):**
- avanzar con traducción y voces mientras se espera a Luna;
- bajar la cantidad de tomas;
- concurrencia de consultas a Luna (batch 6);
- probar large-v3 como transcriptor principal.

## 2. Reglas de trabajo para quien implemente

- Trabajar en este checkout y en esta rama, con commits pequeños por etapa.
  No hacer merge, push ni cambios en el checkout operacional.
- No borrar jobs, cachés, respuestas ni presupuestos. El MP4 original del 16 no
  se sobrescribe. Toda modificación de un job existente pasa por un comando de
  migración bajo su lock, guardando antes una copia del snapshot.
- Antes de gastar GPU o proveedor en una etapa, pasar los tests rápidos y la
  compuerta de corpus (E0).
- Medir siempre por separado: llamadas a Luna (y cuántas inválidas), tomas
  generadas, inferencia Qwen, escuchas Whisper, mezcla, validación y tiempo
  ocioso. No sumar intervalos que se pisan.
- Al terminar cada corrida, entregar un resumen corto con números y detenerse
  para el checkpoint.

---

## 3. Etapas

### E0 — Compuerta de cobertura (sin GPU ni proveedor)

**Para qué:** que ningún cambio vuelva a frenar decenas de frases sin que nos
demos cuenta, como pasó con `79cdcfd`.

- Comando de solo lectura `bin/aidub replay-eligibility JOB --out DIR`, basado
  en `scripts/evaluate_saved_coverage.py`. Recalcula qué frases se doblarían
  con la política vigente. Sin locks ni escrituras en el job.
- Test `tests/test_eligibility_corpus.py`, con expectativas por frase guardadas
  **antes** de cambiar la política:
  - el job oct16 (821) y el clip de 150 s (21);
  - toda diferencia contra la expectativa falla y exige justificación por frase.
- **Aceptación:** reproduce el estado actual (706 elegibles) con la política
  actual.

### E1 — Política permisiva (sin GPU ni proveedor)

En `aidub/fidelity.py` y `aidub/source_disagreement.py`, constante
`ELIGIBILITY_POLICY = "aidub.eligibility.v3"`:

- **Diferencias entre escuchas que no son graves:** la frase se dobla. La
  traducción ya vio ambas lecturas. Se elimina la retención por
  `readings_differ` y la regla de "coincidir con el recorte" de `79cdcfd`.
- **Diferencias graves** (negación o número en un rango cambiado): se
  resuelven con el árbitro de E2. Mientras E2 no exista, la regla es: frase
  larga se dobla con la lectura primaria; frase corta (≤ 2,5 s o ≤ 6 palabras)
  queda retenida.
- **`disputed` del revisor:** se dobla, salvo que sea corta y con diferencia
  grave sin resolver.
- **`revised_unconfirmed`:** se dobla el último texto corregido.
- **`withheld_review_failure` / contrato agotado:** se dobla la última fila
  válida guardada (replay) o el borrador de traducción.
- Se retira del flujo normal el handoff `awaiting_source_review`. El código
  queda para leer estados viejos hasta E7.
- **Reporte:** cada frase doblada con duda queda marcada (`unconfirmed`,
  `reviewer_disputed`, `asr_minor_difference`, `arbiter_majority`). El reporte
  de omisiones pasa a "cobertura X/Y (%) + faltantes por causa".
- **Validación:** las zonas ininteligibles y los eventos sin resolver se
  informan pero no bloquean "completo". `english.mp4` se usa cuando no faltan
  frases doblables. Actualizar `AGENTS.md`, que hoy prohíbe "complete" con
  esas zonas.

**Pruebas:**
- unitarias para cada regla (borde con "No sé" corto y largo; 3300/300 corto;
  conector; disputa; sin confirmar; contrato agotado);
- E0 con las expectativas nuevas.

**Aceptación:** en el replay del 16, las frases retenidas son solo la 457
(tiempo) y las cortas con diferencia grave. **Estimación previa:** 805–818 de 821
elegibles.

### E2 — Whisper large-v3 como árbitro (GPU para ASR; sin Qwen ni proveedor)

- **Descarga autorizada** de los pesos large-v3 (~2,9 GB) al caché local de
  Whisper. No se instalan paquetes ni se toca el entorno. Registrar ruta y
  hash en la configuración local ignorada.
- **Árbitro de frases dudosas** (las que tienen alternativa o disputa):
  - se escucha la frase con large-v3, con margen simétrico y sin truncar por
    los vecinos;
  - la comparación se hace **solo dentro del tramo de tiempo común**: lo que
    queda fuera de la ventana no cuenta como diferencia;
  - votación entre primaria (turbo), segunda escucha (turbo) y large-v3: si dos
    coinciden en el token grave, gana esa lectura;
  - si gana la alternativa y cambia el sentido, una consulta chica a Luna
    retraduce solo esas frases, en batch.
- **Corrector automático para medir:** porcentaje de frases dobladas cuyo
  español coincide con large-v3, y lista de discrepancias graves. Es una
  métrica de seguimiento, no un filtro.
- **Medir** el tiempo de large-v3 sobre las ~124 frases del 16 (estimación:
  pocos minutos).
- **Aceptación:**
  - 3300/300 y "sé"/"no sé" se deciden por mayoría o quedan retenidos solo si
    son cortos;
  - no hay cambios en frases sin duda;
  - caché por WAV, modelo y opciones.

### E3 — Finales de voz: no descartar tomas aprobadas (sin proveedor; GPU solo para reverificar)

Antes de descartar una toma que no entra, en este orden:

1. planificar la aceleración **incluyendo** el final protegido (tope 1,10);
2. fundido del "aire" final por debajo del umbral audible (los últimos ms con
   RMS por debajo de un piso configurable, por ejemplo −50 dBFS), sin tocar la
   voz audible;
3. usar el silencio que quede antes de la voz siguiente, sin moverla;
4. probar otra toma ya aprobada más corta;
5. recién entonces, pedir una frase más corta.

Además:
- toda toma procesada se vuelve a verificar con Whisper;
- se detectan las alineaciones colapsadas (palabras de duración cero) y se
  informan como "límite dudoso" en lugar de pedir texto más corto.

**Pruebas:**
- replay de las tomas guardadas de 402 (seed 7444) y 127 (seed 2169): deben
  entrar con tempo ≤ 1,10;
- 457 sigue afuera;
- los 706 colocados no cambian.

### E4 — Medición de paralelización de Qwen (GPU, minutos)

- `generate_voice_clone` de la versión instalada acepta listas, es decir,
  generación en lote. Script de medición en `tools/`: 8–12 frases reales,
  lote 1 contra lote 4, comparando tiempo y tasa de tomas válidas con los
  controles normales.
- **Si acelera ≥ 1,7× sin bajar la tasa de válidas:** implementar.
  - Identidad de toma = (semilla de lote, índice, tamaño de lote).
  - Las tomas ya cacheadas siguen valiendo con su clave vieja.
  - Las extra de reemplazo se piden en un segundo lote.
- **Si no:** queda documentado y se pospone.
- **No** se lanzan varios procesos Qwen en paralelo.

### E5 — Recuperación del gameplay del 16 (GPU; proveedor solo para las retraducciones de E2)

1. Copia del snapshot y firma del árbol en
   `report/migrations/<fecha>-v3/before/`. El MP4 original no se toca; el nuevo
   export va con otro nombre (`output/english_v3.mp4` o equivalente).
2. Comando `bin/aidub migrate-policy JOB --to aidub.eligibility.v3`, con
   `--dry-run` primero:
   - aplica la política, el replay de decisiones guardadas y el árbitro;
   - importa las 8 colocaciones ya verificadas del estudio v2 (con identidades
     comprobadas);
   - toma el inglés confirmado de 32/62/595/636 del estudio de calificación;
   - registra qué frases cambian y por qué;
   - no resetea presupuestos.
3. **Selección pegajosa:** las frases sin cambios conservan la toma elegida
   antes si sigue válida y entra. Evita que cambien voces ya escuchadas.
4. `bin/aidub auto` normal: síntesis solo de frases nuevas (4 + 4), schedule
   con caché, mezcla, export y validación.
5. **Checkpoint de escucha tuyo:** el video completo o, como mínimo, las frases
   recuperadas. El reporte trae la lista con tiempos.

**Estimación** (no promesa): 805–818 de 821 colocadas. ~60–90 min de
máquina: ~600 tomas nuevas a ~3,2 s más verificación, large-v3 unos minutos,
schedule, mezcla (~5,5 min) y validación (~7 min). Menos si E4 se implementa.

### E6 — Operación desatendida y revisor (proveedor falso en tests; clip real al final)

- **Supervisor (`scripts/overnight.py`):** nunca se rinde ante fallas de
  proveedor o transitorias.
  - Reintenta con esperas crecientes: 5, 15, 30 y 60 minutos, y después cada
    60 minutos.
  - Los errores de cuenta (sesión vencida, cupo) se informan de forma visible
    y se siguen reintentando.
  - Pasado un plazo configurable (por defecto 8 h sin progreso), el pipeline
    exporta lo que haya; las frases sin traducir quedan como "faltantes por
    falla del servicio", distintas de las omisiones normales y reintentables al
    reanudar.
  - Sigue sin hacer fallback a otro proveedor ni a API.
- **Revisor:** `reasoning=high` solo en `review`, con identidad nueva y
  respuestas viejas reutilizables por replay.
  - Contrato simplificado: sin `evidence_id`, sin citar lecturas, sin
    `source_assessment`.
  - `revise` con texto idéntico se toma como `ok` con observación.
- **Huella del video:** solo tamaño y fecha al retomar; la huella completa del
  MP4 final se calcula una vez.
- **Pruebas:**
  - proveedor falso que falla 3 veces y después responde: el job termina sin
    intervención;
  - proveedor caído más allá del plazo: sale el export con faltantes por
    servicio;
  - reanudar no repite llamadas.
  - Al final, el clip de 150 s real con Luna: medir la tasa de respuestas
    inválidas (objetivo < 10 %; hoy 49 %) y el tiempo extra de `high`.

### E7 — Simplificación de código (sin cambiar resultados; E0 debe quedar idéntico)

- Retirar el bucle de resolución de fuente con Luna, la revisión LLM de
  gaps/eventos, `supported_spans` y padres, y la excepción de contexto en
  `quality_flow.load_context` (cuando ningún job activo los use; el del 16 ya
  migrado no los usa).
- Unificar la tokenización española y el conjunto grave (negadores, números).
- Reemplazar los hashes de archivos en identidades por versiones explícitas,
  con un test que falla si cambia el código sin subir la versión. Tabla de
  equivalencias para que los jobs existentes no re-transcriban ni re-escuchen.
- Reducir los estados de revisión a cinco; renombrar los tests `test_batchN`
  por comportamiento; corregir el test legacy desactualizado.
- Reemplazar los hooks `sitecustomize` de estudios por flags del producto
  (`--only-ids`, `--stop-before`, `--frozen-from`).

### E8 — Frases más cortas para gameplays nuevos (sin proveedor en tests; prueba real al final)

- Partir los segmentos en frases de 2–8 s (máximo ~12 s) en pausas ≥ 0,3 s o
  en puntuación de cierre. Se mantiene `utterance_id` como contexto, para que
  la traducción siga sonando a una idea continua.
- Si una frase corta tiene una duda grave sin resolver, se pierde solo esa
  frase y las vecinas se doblan. Así se cumple "perder un pedacito, no la frase
  entera".
- La segunda escucha usa la comparación por tramo común de E2.
- **No se aplica al job del 16:** cambiaría todas las frases.

### E9 — Pruebas reales finales

| Prueba | Input | Qué se mide | Aceptación |
|---|---|---|---|
| Clip | 150 s del 15/10 (ya existente) | Llamadas, inválidos, tiempo, cobertura | Sin intervención; resume con 0 llamadas repetidas |
| **Fragmento** | **10–15 min de una grabación nueva** con reacciones, tramos tranquilos, frases largas y momentos de hablar rápido | Cobertura, tiempos por etapa, frases dudosas dobladas, discrepancias contra large-v3; una interrupción controlada y reanudación | 0 intervenciones; cobertura ≥ 97 % (estimación a confirmar); **escucha tuya** con feedback |
| Larga | Gameplay nuevo de 1–2 h, nocturno | Lo mismo, más tiempo ocioso ≈ 0 | 0 intervenciones; export al despertar |

---

## 4. Roadmap: corridas con checkpoints, no todo de una vez

No conviene hacerlo todo de una vez:
- cada etapa cambia datos que la siguiente necesita (por ejemplo, la política
  y el árbitro definen qué se sintetiza en la recuperación);
- hay dos escuchas tuyas que pueden cambiar el rumbo;
- un error temprano, sin checkpoint, se propaga a 3–4 horas de GPU.

Tampoco conviene una sesión por cada etapa chica. Propongo **6 corridas**:

| # | Contenido | Usa | Checkpoint |
|---|---|---|---|
| 1 | E0 + E1 + E3 (tests y replay de tomas cacheadas), sin migrar el job | CPU; GPU solo para reverificar 2–3 tomas | Te paso la tabla: cuántas frases se recuperarían y cuáles quedan afuera |
| 2 | E2 (descarga e integración de large-v3) + E4 (medición; implementación si conviene) | GPU para ASR y unos minutos de Qwen | Números del árbitro y de la paralelización; decidimos si queda la paralelización |
| 3 | E5: recuperación del video del 16 | GPU ~1–1,5 h; pocas llamadas a Luna | **Escuchás** el video nuevo y me das feedback |
| 4 | Ajustes por tu feedback + E6 (supervisor, revisor high, huella) + clip real | Proveedor falso; después unas pocas llamadas reales | Resumen de tasas e intentos |
| 5 | E8 (frases cortas) + prueba de 10–15 min de una grabación nueva | GPU ~30 min; Luna | **Escuchás** el fragmento y me das feedback |
| 6 | E7 (limpieza de código y docs) + corrida nocturna de 1–2 h | Noche completa | Reporte de la mañana: cobertura, tiempos, intervenciones |

Las corridas 1 y 2 pueden ir en la misma sesión si el contexto lo permite. La
3 conviene empezarla con contexto limpio. Cada corrida termina con commit,
resumen y parada.

**Puntos de vuelta atrás:**
- un commit por etapa;
- copia del snapshot antes de migrar;
- MP4 y job original intactos;
- la política v2 sigue seleccionable por constante hasta E7.
