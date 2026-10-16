package com.cargoclear.japac.di

import com.cargoclear.japac.BuildConfig
import com.cargoclear.japac.core.data.ApiConfig
import android.content.Context
import com.cargoclear.japac.ui.viewer.PdfOpener
import com.cargoclear.japac.ui.viewer.PdfRendererPages
import com.cargoclear.japac.ui.viewer.bitmapBudget
import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.android.qualifiers.ApplicationContext
import dagger.hilt.components.SingletonComponent
import javax.inject.Singleton

@Module
@InstallIn(SingletonComponent::class)
object AppModule {
    @Provides
    @Singleton
    fun apiConfig(): ApiConfig = ApiConfig(BuildConfig.API_BASE_URL)

    /** Pages are drawn into bitmaps no bigger than this phone's heap can afford. */
    @Provides
    fun pdfOpener(@ApplicationContext context: Context): PdfOpener = PdfOpener { PdfRendererPages.open(it, context.bitmapBudget()) }
}
