pluginManagement {
    repositories {
        google {
            content {
                includeGroupByRegex("com\\.android.*")
                includeGroupByRegex("com\\.google.*")
                includeGroupByRegex("androidx.*")
            }
        }
        mavenCentral()
        gradlePluginPortal()
    }
}

dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        google()
        mavenCentral()
    }
}

rootProject.name = "EquitySignalTracker"

// Layer modules. The dependency direction is enforced by what each module declares:
// features → domain → (pure Kotlin); data implements the domain interfaces.
include(":app")

include(":core:common")
include(":core:model")
include(":core:designsystem")
include(":core:network")
include(":core:database")
include(":core:datastore")
include(":core:notifications")

include(":domain")
include(":data")

include(":features:dashboard")
include(":features:scanner")
include(":features:alerts")
include(":features:positions")
include(":features:stockdetails")
include(":features:history")
include(":features:analytics")
include(":features:backtesting")
include(":features:settings")
