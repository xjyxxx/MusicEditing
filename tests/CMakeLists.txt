enable_testing()

add_executable(shared_test shared_test/test_utils.cpp)
target_link_libraries(shared_test PRIVATE media_shared)
add_test(NAME shared_test COMMAND shared_test)
