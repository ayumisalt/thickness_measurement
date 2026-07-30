cmake_minimum_required(VERSION 3.20)
project(thickness_measurement LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

find_package(ROOT 6.32 REQUIRED COMPONENTS Core Graf Gpad Hist MathCore)
find_package(OpenCV 4.8 REQUIRED COMPONENTS core imgcodecs imgproc)
find_package(nlohmann_json 3.11 REQUIRED CONFIG)

add_library(analysis_options INTERFACE)
target_include_directories(analysis_options INTERFACE cpp/include)
target_compile_options(analysis_options INTERFACE -Wall -Wextra -Wpedantic)

add_executable(track_thickness_root cpp/src/track_thickness.cpp)
target_link_libraries(
  track_thickness_root
  PRIVATE analysis_options ROOT::Core ROOT::Graf ROOT::Hist
          ${OpenCV_LIBS} nlohmann_json::nlohmann_json
)
target_include_directories(track_thickness_root PRIVATE ${OpenCV_INCLUDE_DIRS})

add_executable(summarize_result_root cpp/src/summarize_result.cpp)
target_link_libraries(summarize_result_root PRIVATE analysis_options)

add_executable(track_volume_root cpp/src/track_volume.cpp)
target_link_libraries(track_volume_root PRIVATE analysis_options)

add_executable(volume_range_root cpp/src/volume_range.cpp)
target_link_libraries(
  volume_range_root
  PRIVATE analysis_options ROOT::Core ROOT::Graf ROOT::Gpad ROOT::Hist
)

install(
  TARGETS track_thickness_root summarize_result_root track_volume_root
          volume_range_root
  RUNTIME DESTINATION bin
)
