#include "common/utils.h"

#include <cassert>
#include <iostream>

int main() {
    assert(media::common::formatTime(3661.5) == "1:01:01.500");
    assert(media::common::getFileExtension("test.MP4") == "mp4");
    assert(media::common::splitString("a,b,c", ',').size() == 3);
    std::cout << "shared_test passed" << std::endl;
    return 0;
}
