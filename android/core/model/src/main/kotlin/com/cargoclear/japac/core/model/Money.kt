package com.cargoclear.japac.core.model

import java.math.BigDecimal
import java.math.RoundingMode

private const val NBSP = ' '

private fun group(integerDigits: String, indian: Boolean): String {
    if (integerDigits.length <= 3) return integerDigits
    val head = integerDigits.dropLast(3)
    val tail = integerDigits.takeLast(3)
    val size = if (indian) 2 else 3
    val groups = head.reversed().chunked(size).map { it.reversed() }.reversed()
    return groups.joinToString(",") + "," + tail
}

/**
 * "INR 54,43,559.38": the currency code, a no-break space, then the amount grouped in the style of the currency's home market (lakh
 * grouping for INR, thousands elsewhere), always two decimals. Port of `formatMoney` in components/assess/ValuationCard.tsx, whose
 * output (`Intl.NumberFormat`) the tests quote. A value without a currency code reads as USD (as there); a code that is not three
 * letters falls back to the plain number and the code. Done by hand rather than with `java.text` so the result does not depend on the
 * phone's locale or ICU version.
 */
fun formatMoney(value: Double?, currency: String? = null): String {
    if (value == null) return "n/a"
    val code = currency?.takeIf { it.isNotEmpty() } ?: "USD"
    val rounded = BigDecimal.valueOf(value).abs().setScale(2, RoundingMode.HALF_UP)
    if (!Regex("^[A-Za-z]{3}$").matches(code)) {
        return "${BigDecimal.valueOf(value).setScale(2, RoundingMode.HALF_UP).toPlainString()}${currency?.let { " $it" } ?: ""}"
    }
    val plain = rounded.toPlainString()
    val integer = plain.substringBefore('.')
    val fraction = plain.substringAfter('.', "00")
    val negative = value < 0 || (value == 0.0 && 1.0 / value < 0)
    return "${if (negative) "-" else ""}${code.uppercase()}$NBSP${group(integer, indian = code == "INR")}.$fraction"
}

/** "730451" to "7304.51", "73043100" to "7304.31.00": how a tariff code is written; anything else is shown as given. */
fun formatHs(code: String?): String {
    val digits = code.orEmpty().filter { it in '0'..'9' }
    return when (digits.length) {
        6 -> "${digits.take(4)}.${digits.drop(4)}"
        8 -> "${digits.take(4)}.${digits.substring(4, 6)}.${digits.drop(6)}"
        else -> code.orEmpty()
    }
}
