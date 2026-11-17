# Vendored, locally modified copy of ODR-AudioEnc's libtoolame-dab (LGPL 2.1+,
# see LGPL.txt) -- MODIFICATIONS.md lists every change from upstream, chiefly
# DAB mode disabled in toolame.c. pds_subband.c is excluded: it's an
# alternate/unused subband implementation not part of the active build.
file(GLOB TOOLAME_SOURCES ${CMAKE_CURRENT_SOURCE_DIR}/*.c)
list(REMOVE_ITEM TOOLAME_SOURCES ${CMAKE_CURRENT_SOURCE_DIR}/pds_subband.c)

add_library(toolame STATIC ${TOOLAME_SOURCES})
target_include_directories(toolame PUBLIC ${CMAKE_CURRENT_SOURCE_DIR})
target_compile_definitions(toolame PRIVATE NEWENCODE)

if(MSVC)
    target_compile_options(toolame PRIVATE /wd4996 /wd4244 /wd4267 /wd4305)
endif()
