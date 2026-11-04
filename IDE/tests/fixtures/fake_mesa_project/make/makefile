# 假 MESA 桩 makefile：只生成 ./star（真实 MESA 在这里编译）
all: star

star:
	@printf '#!/bin/bash\necho "fake-star: ran (cwd=$(pwd))"\n' > ../star
	@chmod +x ../star

clean:
	@rm -f ../star
	@echo "fake-make: cleaned"
