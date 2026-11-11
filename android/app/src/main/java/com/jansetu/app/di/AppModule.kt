package com.jansetu.app.di

import com.jansetu.app.BuildConfig
import com.jansetu.app.data.SessionStore
import com.jansetu.app.data.remote.ApiFactory
import com.jansetu.app.data.remote.JansetuApi
import com.jansetu.app.data.remote.SessionEvents
import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.components.SingletonComponent
import javax.inject.Singleton

@Module
@InstallIn(SingletonComponent::class)
object AppModule {
    @Provides @Singleton
    fun sessionEvents(): SessionEvents = SessionEvents()

    @Provides @Singleton
    fun api(store: SessionStore, events: SessionEvents): JansetuApi =
        ApiFactory.create(BuildConfig.API_URL, store, events, debug = BuildConfig.DEBUG)
}
