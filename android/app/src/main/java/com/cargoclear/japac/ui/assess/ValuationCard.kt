package com.cargoclear.japac.ui.assess

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.cargoclear.japac.R
import com.cargoclear.japac.core.model.ValuationEstimate
import com.cargoclear.japac.core.model.ValuationStatus
import com.cargoclear.japac.core.model.formatHs
import com.cargoclear.japac.core.model.formatMoney
import com.cargoclear.japac.ui.common.PlainCard
import com.cargoclear.japac.ui.common.SectionHeading
import com.cargoclear.japac.ui.common.Tag
import com.cargoclear.japac.ui.theme.cargo
import kotlin.math.abs

@Composable
private fun MoneyRow(label: String, value: String, strong: Boolean = false) {
    val tokens = MaterialTheme.cargo
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.Top) {
        Text(
            label,
            Modifier.weight(1f).padding(end = 12.dp),
            color = if (strong) tokens.text else tokens.textMuted,
            fontWeight = if (strong) FontWeight.SemiBold else FontWeight.Normal,
            style = MaterialTheme.typography.bodySmall,
        )
        Text(value, color = tokens.text, fontFamily = FontFamily.Monospace, fontWeight = if (strong) FontWeight.Bold else FontWeight.Normal, fontSize = 13.sp)
    }
}

/**
 * Indicative assessable value and duty exposure (port of components/assess/ValuationCard.tsx). Information for the authorised agent:
 * never the status, never an amount payable. The disclaimer, every assumption and the rule set are always shown or one tap away.
 */
@Composable
fun ValuationCard(valuation: ValuationEstimate, modifier: Modifier = Modifier) {
    val v = valuation
    val tokens = MaterialTheme.cargo
    val invoiceCurrency = v.invoiceCurrency.orEmpty()
    val destinationCurrency = v.destinationCurrency.orEmpty()
    var assumptionsOpen by rememberSaveable { mutableStateOf(false) }

    PlainCard(modifier) {
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.Top) {
            SectionHeading(
                text = stringResource(
                    R.string.valuation_title,
                    v.destinationCountry,
                    v.hsCode?.takeIf { it.isNotEmpty() }?.let { stringResource(R.string.valuation_title_hs, formatHs(it)) }.orEmpty(),
                ),
                modifier = Modifier.weight(1f).padding(end = 8.dp),
            )
            Tag(
                text = stringResource(
                    when (v.status) {
                        ValuationStatus.ESTIMATED -> R.string.valuation_estimate
                        ValuationStatus.PARTIAL -> R.string.valuation_partial
                        ValuationStatus.NOT_AVAILABLE -> R.string.valuation_not_available
                    },
                ).uppercase(),
            )
        }

        Text(v.disclaimer, color = tokens.textMuted, style = MaterialTheme.typography.bodySmall)

        v.reason?.takeIf { it.isNotEmpty() }?.let { reason ->
            Text(
                text = stringResource(if (v.status == ValuationStatus.NOT_AVAILABLE) R.string.valuation_no_estimate else R.string.valuation_incomplete, reason),
                color = tokens.warn.fg,
                fontWeight = FontWeight.Medium,
                style = MaterialTheme.typography.bodySmall,
            )
        }

        v.transactionValue?.let { transaction ->
            Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                MoneyRow(
                    stringResource(R.string.valuation_transaction_value, v.incoterm?.takeIf { it.isNotEmpty() }?.let { stringResource(R.string.valuation_incoterm, it) }.orEmpty()),
                    formatMoney(transaction, invoiceCurrency),
                )
                v.freight?.let { MoneyRow(stringResource(R.string.valuation_freight), formatMoney(it, invoiceCurrency)) }
                v.insurance?.let { MoneyRow(stringResource(R.string.valuation_insurance), formatMoney(it, invoiceCurrency)) }
                v.assessableValue?.let {
                    MoneyRow(
                        stringResource(R.string.valuation_assessable, v.exchangeRate?.let(::plainNumber) ?: "?", invoiceCurrency, destinationCurrency),
                        formatMoney(it, destinationCurrency),
                        strong = true,
                    )
                }
            }
        }

        if (v.duties.isNotEmpty()) {
            Column {
                v.duties.forEach { line ->
                    HorizontalDivider(color = tokens.border)
                    Column(Modifier.padding(vertical = 6.dp), verticalArrangement = Arrangement.spacedBy(2.dp)) {
                        MoneyRow(line.name, formatMoney(line.amount, destinationCurrency), strong = true)
                        Text(
                            text = (line.ratePct?.let { stringResource(R.string.valuation_rate_pct, plainNumber(it)) } ?: stringResource(R.string.valuation_rate_na)) +
                                (line.base?.let { stringResource(R.string.valuation_of_base, formatMoney(it, destinationCurrency)) } ?: "") +
                                (line.note?.takeIf { it.isNotEmpty() }?.let { " · $it" } ?: ""),
                            color = tokens.textMuted,
                            fontSize = 11.sp,
                        )
                    }
                }
                HorizontalDivider(color = tokens.borderStrong, thickness = 2.dp)
                Row(Modifier.fillMaxWidth().padding(top = 6.dp), horizontalArrangement = Arrangement.SpaceBetween) {
                    Text(stringResource(R.string.valuation_total), color = tokens.text, fontWeight = FontWeight.Bold, style = MaterialTheme.typography.bodyMedium)
                    Text(formatMoney(v.totalDuty, destinationCurrency), color = tokens.text, fontFamily = FontFamily.Monospace, fontWeight = FontWeight.Bold)
                }
            }
        }

        val implied = v.impliedTotalDuty
        if (!v.impliedHsCode.isNullOrEmpty() && implied != null) {
            val unchanged = abs(implied - (v.totalDuty ?: 0.0)) < 0.005
            Text(
                text = if (unchanged) {
                    stringResource(R.string.valuation_implied_unchanged, formatHs(v.impliedHsCode))
                } else {
                    stringResource(R.string.valuation_implied_changed, formatHs(v.impliedHsCode), formatMoney(implied, destinationCurrency))
                },
                color = tokens.textMuted,
                style = MaterialTheme.typography.bodySmall,
            )
        }

        if (v.assumptions.isNotEmpty()) {
            Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Text(
                    text = (if (assumptionsOpen) "▾ " else "▸ ") + stringResource(R.string.valuation_assumptions, v.assumptions.size),
                    modifier = Modifier.clickable(role = Role.Button) { assumptionsOpen = !assumptionsOpen }.padding(vertical = 6.dp),
                    color = tokens.text,
                    fontWeight = FontWeight.SemiBold,
                    style = MaterialTheme.typography.bodySmall,
                )
                if (assumptionsOpen) v.assumptions.forEach { Text("• $it", color = tokens.textMuted, style = MaterialTheme.typography.bodySmall) }
            }
        }

        v.ruleSet?.takeIf { it.isNotEmpty() }?.let { ruleSet ->
            Text(
                text = stringResource(R.string.valuation_rule_set, ruleSet) + (v.regulationRef?.takeIf { it.isNotEmpty() }?.let { stringResource(R.string.valuation_regulation, it) } ?: ""),
                color = tokens.textSubtle,
                fontSize = 11.sp,
            )
        }
    }
}

/** A number the way the web prints it in a sentence (`${v.rate_pct}%`, `${v.exchange_rate}`): 18.0 is "18". */
private fun plainNumber(value: Double): String =
    java.math.BigDecimal.valueOf(value).stripTrailingZeros().toPlainString()
