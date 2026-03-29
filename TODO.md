- Optimize dropdowns, because they render all elements but with css hidden, so they are actually present in HTML, and loading 4k+ files really hurts :D
- Add some section for including master frames, because the are actually used for more than single night
- Lets do some processing :)
- Figure out the integration of dark/flat frames, if we got them instead of master frames

- Where we left:
file:///home/patrick115/Projects/VSB/Semester8/SemestralProject/astro-grader/src/lib/components/preview/image-info.svelte#L16
 - Render the  image info + add the dropdown with debayering options, and react on them, then if you select some debayering option, we need to call the 
file:///home/patrick115/Projects/VSB/Semester8/SemestralProject/astro-grader/src-tauri/src/fits/file.rs#L96 function with the diferent debayering option, also add dropdown for downscaling (where the debayering = 50% downscaling automatically) in future we add more debayering options, but for now we only add the true RGB, by scaling image to 50%