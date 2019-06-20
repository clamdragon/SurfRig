The end-user release herein is SurfRig. SurfRig is a PyMel tool for mesh-agnostic NURBS surface-based rigging. Create arbitrary surfaces and add joints that animate by sliding along them. Limit the joints' movement within the surface. Make weighted parent controls in custom configurations to easily provide major-minor workflow. Use any deformers on the surfaces to get great results (blendshapes, muscle, clusters), with it all baking down to joint data.

Originally intended for face rigging, as joints sliding over surfaces mimic flesh sliding over bone.

Included in download is the bkTools utilities package, which is a collection of functions for Maya.
Also included is Qt.py (made and maintained here: https://github.com/mottosso/Qt.py)

INSTALLATION AND USE:
1) Put bkTools in a Maya python visible directory ("your directory").

&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;To do this with git, navigate to your directory and do:
`git clone https://github.com/clamdragon/SurfRig.git bkTools`

&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;OR, download as ZIP and unzip into your directory. Unzipped folder needs to be renamed "bkTools".

2) To use SurfRig, execute the following python code from inside Maya:
`from bkTools import surfRig; surfRig.main()`

Demo videos here:
https://vimeo.com/253358401
https://vimeo.com/254054248
