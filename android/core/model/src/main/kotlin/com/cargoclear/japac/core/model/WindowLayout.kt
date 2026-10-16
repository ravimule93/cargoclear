package com.cargoclear.japac.core.model

/**
 * Whether the bundle screen shows the assessment and the document side by side (as the web workbench does) instead of one pane behind a
 * tab bar. Needs a window of at least 840 dp across (Material's "expanded" width: a tablet, an unfolded foldable, a large window) and 480 dp
 * down, so a phone turned on its side, which is wide but not tall, keeps one pane. A 600 dp "medium" window is too narrow to split.
 */
fun isTwoPane(widthDp: Int, heightDp: Int): Boolean = widthDp >= TWO_PANE_MIN_WIDTH_DP && heightDp >= TWO_PANE_MIN_HEIGHT_DP

const val TWO_PANE_MIN_WIDTH_DP: Int = 840
const val TWO_PANE_MIN_HEIGHT_DP: Int = 480
