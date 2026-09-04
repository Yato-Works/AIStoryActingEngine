cmake_minimum_required(VERSION 3.24)

project(AIStoryActingEngineDesktop
    VERSION 0.1.0
    DESCRIPTION "AIStoryActingEngine Desktop — Phase 3 skeleton (Qt6/QML + C++20 Core)"
    LANGUAGES CXX
)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

set(CMAKE_AUTOMOC ON)
set(CMAKE_INCLUDE_CURRENT_DIR ON)

find_package(Qt6 REQUIRED COMPONENTS Core Gui Quick QuickControls2 Multimedia)
qt_policy(SET QTP0004 NEW)

qt6_add_executable(aiae_desktop
    src/main.cpp
    src/WorkerBridge.h
    src/WorkerBridge.cpp
)

qt6_add_qml_module(aiae_desktop
    URI AIAE
    VERSION 1.0
    QML_FILES
        src/Main.qml
        src/BookshelfPage.qml
        src/PlayerPage.qml
        src/CastingPage.qml
        src/VoiceStudioPage.qml
        src/StudioPage.qml
        src/NowPlayingBar.qml
)

target_link_libraries(aiae_desktop PRIVATE
    Qt6::Core
    Qt6::Gui
    Qt6::Quick
    Qt6::QuickControls2
    Qt6::Multimedia
)

if(WIN32)
    set_target_properties(aiae_desktop PROPERTIES WIN32_EXECUTABLE TRUE)
endif()