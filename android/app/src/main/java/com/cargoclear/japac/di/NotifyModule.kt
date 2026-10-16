package com.cargoclear.japac.di

import com.cargoclear.japac.notify.NotificationsEnabled
import com.cargoclear.japac.notify.RunNotifier
import com.cargoclear.japac.notify.RunWatchScheduler
import com.cargoclear.japac.notify.WorkManagerRunWatchScheduler
import dagger.Binds
import dagger.Module
import dagger.hilt.InstallIn
import dagger.hilt.components.SingletonComponent

@Module
@InstallIn(SingletonComponent::class)
abstract class NotifyModule {
    @Binds
    abstract fun runWatchScheduler(impl: WorkManagerRunWatchScheduler): RunWatchScheduler

    @Binds
    abstract fun notificationsEnabled(impl: RunNotifier): NotificationsEnabled
}
