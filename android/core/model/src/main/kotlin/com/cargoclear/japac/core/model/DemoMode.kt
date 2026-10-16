package com.cargoclear.japac.core.model

/** Same text as `DEMO_BANNER_TEXT` in frontend/components/shell/DemoBanner.tsx. */
const val DEMO_BANNER_TEXT: String =
    "DEMO MODE - extraction uses synthetic fixtures keyed on filename, not a real document reading."

/** Whether the demo banner applies: demo app mode, or the assessment says it came from fixtures. */
fun isDemoData(appMode: AppMode?, dataSource: DataSource?): Boolean =
    appMode == AppMode.DEMO || dataSource == DataSource.FIXTURE
